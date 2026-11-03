import pytest

from contract_driven_ai_flow.research.workbench.analysis import analyze_source
from contract_driven_ai_flow.research.workbench.source_occurrences import source_occurrences


def collect(tmp_path, text, displayed_text=None):
    path = tmp_path / "analysis.py"
    path.write_text(text, encoding="utf-8")
    analysis = analyze_source(path)
    return analysis, source_occurrences(analysis, displayed_text or text)


def group(groups, name, scope="<module>"):
    return next(item for item in groups if item["name"] == name and item["scope"] == scope)


def spans(item):
    return [(span["line"], span["column"], span["end_column"], span["role"]) for span in item["occurrences"]]


def test_repeated_definitions_and_uses_are_exact_tokens_in_one_scope(tmp_path):
    analysis, groups = collect(tmp_path, 'x = 1; x = x + 2\ny = x\ntext = "x"  # x\ndef f(x):\n    x = x + 1\n    return x\n')
    outer = group(groups, "x")
    assert spans(outer) == [(1, 0, 1, "definition"), (1, 7, 8, "definition"), (1, 11, 12, "use"), (2, 4, 5, "use")]
    assert outer["object_ids"] == [obj.id for obj in analysis.objects if obj.name == "x" and obj.scope == "<module>"]
    assert spans(group(groups, "x", "f")) == [(4, 6, 7, "definition"), (5, 4, 5, "definition"), (5, 8, 9, "use"), (6, 11, 12, "use")]


def test_future_local_binding_never_becomes_a_global_use(tmp_path):
    _, groups = collect(tmp_path, "x = 1\ndef f():\n    print(x)\n    x = 2\n    return x\n")
    assert [span["line"] for span in group(groups, "x")["occurrences"]] == [1]
    assert [span["line"] for span in group(groups, "x", "f")["occurrences"]] == [3, 4, 5]


def test_global_and_nonlocal_writes_keep_historical_ids_as_lexical_aliases(tmp_path):
    analysis, groups = collect(tmp_path, "x = 1\ndef outer():\n    y = 2\n    def inner():\n        global x\n        nonlocal y\n        x = y\n        y += x\n        return x + y\n    return inner()\n")
    outer_x, outer_y = group(groups, "x"), group(groups, "y", "outer")
    assert {obj.id for obj in analysis.objects if obj.name == "x"} == set(outer_x["object_ids"])
    assert {obj.id for obj in analysis.objects if obj.name == "y"} == set(outer_y["object_ids"])
    assert [span["line"] for span in outer_x["occurrences"]] == [1, 5, 7, 8, 9]
    assert [span["line"] for span in outer_y["occurrences"]] == [3, 6, 7, 8, 9]
    assert len(outer_x["logical_keys"]) == len(outer_y["logical_keys"]) == 2


def test_comprehension_bindings_do_not_shadow_their_outer_iterator_or_escape(tmp_path):
    _, groups = collect(tmp_path, "i = [1, 2]\nresult = [i + 1 for i in i if i > 0]\nafter = i\n")
    assert spans(group(groups, "i")) == [(1, 0, 1, "definition"), (2, 25, 26, "use"), (3, 8, 9, "use")]
    local = next(item for item in groups if item["name"] == "i" and item["scope"] != "<module>")
    assert sorted(span["column"] for span in local["occurrences"]) == [10, 20, 30]


def test_comprehension_walrus_target_belongs_to_the_enclosing_scope(tmp_path):
    _, groups = collect(tmp_path, "values = [1]\nresult = [(last := item) for item in values]\nafter = last\n")
    assert spans(group(groups, "last")) == [(2, 11, 15, "definition"), (3, 8, 12, "use")]


def test_function_defaults_lambda_bodies_and_class_methods_resolve_python_scopes(tmp_path):
    _, groups = collect(tmp_path, "x = 1\nf = lambda x=x: x\nclass C:\n    x = 2\n    def m(self, y=x):\n        return x + y\n")
    assert [span["line"] for span in group(groups, "x")["occurrences"]] == [1, 2, 6]
    assert [span["line"] for span in group(groups, "x", "C")["occurrences"]] == [4, 5]
    lambda_x = next(item for item in groups if item["name"] == "x" and "<lambda>" in item["scope"])
    assert [span["role"] for span in lambda_x["occurrences"]] == ["definition", "use"]


def test_separate_same_named_function_definitions_do_not_merge_local_bindings(tmp_path):
    analysis, groups = collect(tmp_path, "def f():\n    x = 1\n    return x\ndef f():\n    x = 2\n    return x\n")
    xs = [item for item in groups if item["name"] == "x"]
    assert len(xs) == 2
    assert len({item["logical_key"] for item in xs}) == 2
    assert [len(item["object_ids"]) for item in xs] == [1, 1]
    assert {item["object_ids"][0] for item in xs} == {obj.id for obj in analysis.objects if obj.name == "x"}


def test_utf8_ast_columns_are_converted_to_javascript_utf16_offsets(tmp_path):
    _, groups = collect(tmp_path, '"😀"; 值 = 1; print(值)\n')
    assert spans(group(groups, "值")) == [(1, 6, 7, "definition"), (1, 19, 20, "use")]


def test_display_redaction_changes_columns_without_changing_assignment_identity(tmp_path):
    analysis, groups = collect(tmp_path, 'password = "long credential"; x = 1; x = x + 1\n', 'password = "[REDACTED]"; x = 1; x = x + 1\n')
    x = group(groups, "x")
    assert x["object_ids"] == [obj.id for obj in analysis.objects if obj.name == "x"]
    assert [(span["column"], span["role"]) for span in x["occurrences"]] == [(25, "definition"), (32, "definition"), (36, "use")]


def test_global_subscript_mutation_is_part_of_the_outer_variable_history(tmp_path):
    analysis, groups = collect(tmp_path, "x = [0]\ndef update():\n    global x\n    x[0] = x[0] + 1\n    return x\n")
    x = group(groups, "x")
    assert x["object_ids"] == [obj.id for obj in analysis.objects if obj.name == "x"]
    assert any(span["line"] == 4 and span["role"] == "definition" for span in x["occurrences"])


@pytest.mark.parametrize("header", [
    "def inner(a: (v := x)):",
    "def inner(a: (v := x), /):",
    "def inner(*, a: (v := x)):",
    "def inner(*a: (v := x)):",
    "def inner(**a: (v := x)):",
    "def inner() -> (v := x):",
    "async def inner(a: (v := x)) -> int:",
])
def test_nested_function_annotation_walrus_binds_the_enclosing_scope(tmp_path, header):
    _, groups = collect(tmp_path, f"v = 0\nx = 1\ndef outer():\n    {header}\n        return v\n    return v\n")
    assert [span["line"] for span in group(groups, "v")["occurrences"]] == [1]
    assert [(span["line"], span["role"]) for span in group(groups, "v", "outer")["occurrences"]] == [(4, "definition"), (5, "use"), (6, "use")]
    assert {item["scope"] for item in groups if item["name"] == "v"} == {"<module>", "outer"}


def test_collecting_nested_annotations_keeps_the_nested_body_out_of_outer_bindings(tmp_path):
    _, groups = collect(tmp_path, "v = 0\nx = 1\nbody_only = 99\ndef outer():\n    def inner(a: (v := x)):\n        body_only = 2\n        return v + body_only\n    return v + body_only\n")
    assert [span["line"] for span in group(groups, "v", "outer")["occurrences"]] == [5, 7, 8]
    assert [span["line"] for span in group(groups, "body_only")["occurrences"]] == [3, 8]
    assert [span["line"] for span in group(groups, "body_only", "outer.inner")["occurrences"]] == [6, 7]


def test_class_assignment_rhs_reads_outer_name_before_class_binding_exists(tmp_path):
    _, groups = collect(tmp_path, "x = 1\nclass C:\n    x = x + 1\n")
    assert spans(group(groups, "x")) == [(1, 0, 1, "definition"), (3, 8, 9, "use")]
    assert spans(group(groups, "x", "C")) == [(3, 4, 5, "definition")]


def test_class_reads_use_only_prior_class_bindings_and_methods_skip_class_namespace(tmp_path):
    _, groups = collect(tmp_path, "x = 1\nclass C:\n    y = x\n    x = 2\n    z = x\n    def method(self):\n        return x\n")
    assert [(span["line"], span["role"]) for span in group(groups, "x")["occurrences"]] == [(1, "definition"), (3, "use"), (7, "use")]
    assert [(span["line"], span["role"]) for span in group(groups, "x", "C")["occurrences"]] == [(4, "definition"), (5, "use")]


def test_class_local_load_name_falls_back_to_module_while_method_captures_outer_function(tmp_path):
    _, groups = collect(tmp_path, "x = 1\ndef outer():\n    x = 2\n    class C:\n        y = x\n        x = x + 1\n        z = x\n        def method(self):\n            return x\n    return C\n")
    assert [span["line"] for span in group(groups, "x")["occurrences"]] == [1, 5, 6]
    assert [span["line"] for span in group(groups, "x", "outer")["occurrences"]] == [3, 9]
    assert [(span["line"], span["role"]) for span in group(groups, "x", "outer.C")["occurrences"]] == [(6, "definition"), (7, "use")]


def test_class_free_name_without_a_local_class_declaration_uses_outer_function_binding(tmp_path):
    _, groups = collect(tmp_path, "x = 1\ndef outer():\n    x = 2\n    class C:\n        y = x\n        def method(self):\n            return x\n    return C\n")
    assert [span["line"] for span in group(groups, "x")["occurrences"]] == [1]
    assert [span["line"] for span in group(groups, "x", "outer")["occurrences"]] == [3, 5, 7]


def test_class_function_default_is_read_before_its_name_is_bound(tmp_path):
    _, groups = collect(tmp_path, "f = 1\nclass C:\n    def f(a=f):\n        return a\n")
    assert [(span["line"], span["role"]) for span in group(groups, "f")["occurrences"]] == [(1, "definition"), (3, "use")]
    assert [span["role"] for span in group(groups, "f", "C")["occurrences"]] == ["definition"]


def test_class_loop_iterable_is_read_before_its_target_creates_a_class_binding(tmp_path):
    _, groups = collect(tmp_path, "x = [1]\nclass C:\n    for x in x:\n        pass\n    after = x\n")
    assert [(span["line"], span["role"]) for span in group(groups, "x")["occurrences"]] == [(1, "definition"), (3, "use")]
    assert [(span["line"], span["role"]) for span in group(groups, "x", "C")["occurrences"]] == [(3, "definition"), (5, "use")]


def test_deleted_class_binding_no_longer_shadows_the_outer_name(tmp_path):
    _, groups = collect(tmp_path, "x = 1\nclass C:\n    x = 2\n    del x\n    after = x\n")
    assert [span["line"] for span in group(groups, "x")["occurrences"]] == [1, 5]
    assert [span["line"] for span in group(groups, "x", "C")["occurrences"]] == [3, 4]


def test_initial_class_augmented_assignment_reads_outer_value_and_defines_class_value(tmp_path):
    _, groups = collect(tmp_path, "x = 1\nclass C:\n    x += 1\n    after = x\n")
    assert [(span["line"], span["role"]) for span in group(groups, "x")["occurrences"]] == [(1, "definition"), (3, "use")]
    assert [(span["line"], span["role"]) for span in group(groups, "x", "C")["occurrences"]] == [(3, "definition"), (4, "use")]

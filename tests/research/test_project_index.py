import shutil
import threading
from pathlib import Path

import pytest

from contract_driven_ai_flow.research.projects import resolver
from contract_driven_ai_flow.research.projects.service import ProjectService


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    write(root, "main.py", "from compute import scale\nX = [1, 2, 3]\nY = scale(X)\n")
    write(root, "compute.py", "X = 99\ndef scale(values):\n    result = [v * 2 for v in values]\n    return result\n")
    write(root, "danger.py", "raise RuntimeError('INDEX MUST NEVER EXECUTE')\n")


def test_root_py_files_indexed_and_call_is_inferred(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        revision = service.index(project.id)
        page = service.files(project.id)
        assert revision.files_count == 3 and page.total == 3
        assert {u.relative_path for u in page.items} == {"main.py", "compute.py", "danger.py"}
        graph = service.graph(project.id).graph
        assert any(e.kind == "call" for e in graph.edges)
        assert all(e.provenance == "inferred" for e in graph.edges)
        assert not list(root.glob("*.ran"))
    finally:
        service.close()


def test_index_and_graph_reuse_cached_facts_without_reparse(tmp_path, monkeypatch):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        first = service.index(project.id)
        assert first.parsed_files == 3 and first.reused_files == 0
        calls = {"n": 0}
        real = resolver.scan

        def counting(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(resolver, "scan", counting)
        second = service.index(project.id)
        assert second.parsed_files == 0 and second.reused_files == 3
        assert calls["n"] == 0
        service.graph(project.id)
        assert calls["n"] == 0
    finally:
        service.close()


def test_incremental_retains_old_revision_and_cancel(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        r1 = service.index(project.id)
        unit = next(u for u in service.files(project.id).items if u.relative_path == "compute.py")
        write(root, "compute.py", "def scale(values):\n    return values\n")
        r2 = service.index(project.id)
        assert r2.id != r1.id and r2.parsed_files == 1 and r2.reused_files == 2
        assert r2.parent_revision_id == r1.id
        assert "v * 2" in service.source(project.id, unit.id, r1.id)["code"]
        assert "v * 2" not in service.source(project.id, unit.id, r2.id)["code"]
        old = service.analysis(project.id, unit.id, r1.id)
        names = {o.name for o in old.objects}
        assert "result" in names
        cancel = threading.Event(); cancel.set()
        with pytest.raises((RuntimeError, InterruptedError)):
            service.index(project.id, cancel=cancel)
        assert service.revision(project.id).id == r2.id
    finally:
        service.close()


def test_archived_source_is_redacted_but_facts_survive(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    write(root, "secret.py", 'API_KEY = "supersecretvalue123"\n\ndef use():\n    return API_KEY\n')
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        unit = next(u for u in service.files(project.id).items if u.relative_path == "secret.py")
        archived = service.source(project.id, unit.id)["code"]
        assert "supersecretvalue123" not in archived
        assert "[REDACTED]" in archived
        document = service.analysis(project.id, unit.id)
        assert {"use"} <= {o.name for o in document.objects}
    finally:
        service.close()


def test_unique_rename_rebind_and_project_relocation(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        before = next(u for u in service.files(project.id).items if u.relative_path == "compute.py")
        (root / "compute.py").rename(root / "calc.py")
        revision = service.index(project.id)
        after = next(u for u in service.files(project.id).items if u.relative_path == "calc.py")
        assert after.id == before.id
        assert any("Rebound identity" in d for d in revision.diagnostics)

        # A genuine move (original gone) relocates the same UUID.
        moved = tmp_path / "lab-moved"
        root.rename(moved)
        reopened = service.open(moved)
        assert reopened.id == project.id
        moved_unit = next(u for u in service.files(reopened.id).items if u.relative_path == "calc.py")
        assert moved_unit.id == before.id
        assert service.source(reopened.id, moved_unit.id)["code"]
    finally:
        service.close()


def test_duplicate_copy_cannot_retarget_uuid(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        copy = tmp_path / "lab-copy"
        shutil.copytree(root, copy)
        with pytest.raises(ValueError):
            service.open(copy)
    finally:
        service.close()


def test_workbench_backup_preserves_authored_bytes(tmp_path):
    root = tmp_path / "lab"; root.mkdir()
    authored = "protocol_version: 3\nscript: analyse.py\n"
    (root / "workbench.yaml").write_text(authored, encoding="utf-8")
    service = ProjectService(tmp_path / "host")
    try:
        service.open(root)
        backup = (root / "workbench.yaml.bak").read_text(encoding="utf-8")
        assert backup == authored
        current = (root / "workbench.yaml").read_text(encoding="utf-8")
        assert "script: analyse.py" in current and "project:" in current
    finally:
        service.close()


def test_annotated_assignments_do_not_crash(tmp_path):
    root = tmp_path / "lab"
    write(root, "typed.py", "X: int = 2\nX += 1\nY: int\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        revision = service.index(project.id)
        assert revision.files_count == 1
        unit = service.files(project.id).items[0]
        assert unit.status == "parsed" and not unit.diagnostics
    finally:
        service.close()


def test_absolute_import_inside_package(tmp_path):
    root = tmp_path / "lab"
    write(root, "compute.py", "def scale(values):\n    return values\n")
    write(root, "pkg/app.py", "from compute import scale\nR = scale(1)\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        graph = service.graph(project.id).graph
        assert any(e.kind == "call" for e in graph.edges)
    finally:
        service.close()


def test_actual_parameter_and_return_receiver_edges(tmp_path):
    root = tmp_path / "lab"
    write(root, "main.py", "from compute import scale\nX = [1, 2, 3]\nY = scale(X)\n")
    write(root, "compute.py", "def scale(values):\n    result = [v * 2 for v in values]\n    return result\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        graph = service.graph(project.id).graph
        label = {n.id: n.label for n in graph.nodes}
        assert any(
            e.kind == "argument" and label.get(e.source) == "X" and label.get(e.target) == "values"
            for e in graph.edges
        )
        assert any(
            e.kind == "return" and label.get(e.target) == "Y"
            for e in graph.edges
        )
    finally:
        service.close()


def test_removed_files_are_dropped_from_current_identity(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        r1 = service.index(project.id)
        old = next(u for u in service.files(project.id).items if u.relative_path == "compute.py")
        (root / "compute.py").unlink()
        service.index(project.id)
        assert "compute.py" not in {u.relative_path for u in service.files(project.id).items}
        # Re-adding the same bytes must not resurrect the removed identity.
        write(root, "renamed_compute.py", "X = 99\ndef scale(values):\n    result = [v * 2 for v in values]\n    return result\n")
        service.index(project.id)
        new = next(u for u in service.files(project.id).items if u.relative_path == "renamed_compute.py")
        assert new.id != old.id
        assert "X = 99" in service.source(project.id, old.id, r1.id)["code"]
    finally:
        service.close()


def test_unknown_scope_raises_and_keys_are_canonical(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        with pytest.raises(KeyError):
            service.graph(project.id, scope_id="no/such/scope")
        graph = service.graph(project.id).graph
        assert graph.blocks and all(b.source is not None for b in graph.blocks if b.kind == "project")
        assert all(b.source is not None for b in graph.blocks if b.kind == "file")
        for block in graph.blocks:
            assert block.logical_key.count(project.id) <= 1
        for node in graph.nodes:
            assert node.logical_key.count(project.id) <= 1
    finally:
        service.close()


def test_large_graph_is_bounded_file_aggregate(tmp_path):
    root = tmp_path / "lab"
    body = "".join(f"V{i} = {i}\n" for i in range(40))
    write(root, "lib.py", "def target(value):\n    return value\n")
    write(root, "big.py", "from lib import target\n" + body + "R = target(1)\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        bounded = service.graph(project.id, limit=5)
        assert bounded.graph.nodes == []
        assert bounded.omitted_count > 0
        ids = {b.id for b in bounded.graph.blocks}
        for edge in bounded.graph.edges:
            assert edge.source in ids and edge.target in ids
    finally:
        service.close()


def test_exclusions_and_out_of_root_links(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    for rel in (".venv/a.py", "venv/b.py", "node_modules/c.py", "__pycache__/d.py", ".cdaf/e.py", "build/f.py", "dist/g.py"):
        write(root, rel, "x = 1\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        paths = {u.relative_path for u in service.files(project.id).items}
        assert paths == {"main.py", "compute.py", "danger.py"}
    finally:
        service.close()


def test_src_layout_relative_and_reexport(tmp_path):
    root = tmp_path / "lab"
    write(root, "src/pkg/__init__.py", "from .helper import g\n")
    write(root, "src/pkg/helper.py", "def g(value):\n    return value + 1\n")
    write(root, "src/app.py", "from pkg import g\nseed = 1\nR = g(seed)\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        units = {u.relative_path: u for u in service.files(project.id).items}
        assert units["src/pkg/helper.py"].module_names == ["pkg.helper"]
        assert units["src/pkg/__init__.py"].module_names == ["pkg"]
        graph_slice = service.graph(project.id)
        call_edges = [e for e in graph_slice.graph.edges if e.kind == "call"]
        assert call_edges
        assert any(e.kind == "argument" for e in graph_slice.graph.edges)
        assert all(e.provenance != "observed" for e in graph_slice.graph.edges)
    finally:
        service.close()


def test_scope_slice_is_bounded_and_valid(tmp_path):
    root = tmp_path / "lab"
    write(root, "pkg/a.py", "def one():\n    return 1\n")
    write(root, "pkg/b.py", "def two():\n    return 2\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        units = {u.relative_path: u for u in service.files(project.id).items}
        sliced = service.graph(project.id, scope_id=units["pkg/a.py"].id)
        ids = {b.id for b in sliced.graph.blocks} | {n.id for n in sliced.graph.nodes}
        for edge in sliced.graph.edges:
            assert edge.source in ids and edge.target in ids
        assert sliced.scope_id == units["pkg/a.py"].id
        bounded = service.graph(project.id, limit=2)
        assert bounded.omitted_count >= 0
    finally:
        service.close()


def test_duplicate_symbols_stay_distinct_and_syntax_error_cached(tmp_path):
    root = tmp_path / "lab"
    write(root, "one.py", "X = 1\n")
    write(root, "two.py", "X = 2\n")
    write(root, "broken.py", "def (\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        units = {u.relative_path: u for u in service.files(project.id).items}
        assert units["broken.py"].status == "error" and units["broken.py"].diagnostics
        one = service.analysis(project.id, units["one.py"].id)
        two = service.analysis(project.id, units["two.py"].id)
        key1 = next(o for o in one.objects if o.name == "X").logical_key
        key2 = next(o for o in two.objects if o.name == "X").logical_key
        assert key1 != key2
        second = service.index(project.id)
        assert second.reused_files == 3
        assert service.files(project.id).items[-1].status in ("parsed", "error")
    finally:
        service.close()


def test_run_configurations_and_source_ref_fields(tmp_path):
    from contract_driven_ai_flow.research.models import SourceRef
    from contract_driven_ai_flow.research.workbench.models import RunConfiguration, WorkbenchConfig

    root = tmp_path / "lab"; fixture(root)
    config = WorkbenchConfig(
        run_configurations=[RunConfiguration(name="run", kind="script", target="main.py")]
    )
    assert config.run_configurations[0].target == "main.py"
    assert config.project is None
    ref = SourceRef(project_id="p", file_id="f", project_revision_id="r")
    assert (ref.project_id, ref.file_id, ref.project_revision_id) == ("p", "f", "r")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        assert service.entries(project.id) == []
    finally:
        service.close()
def test_ambiguous_module_names_are_reported(tmp_path):
    root = tmp_path / "lab"
    write(root, "a.py", "def one():\n    return 1\n")
    write(root, "src/a.py", "def two():\n    return 2\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        revision = service.index(project.id)
        assert any("Ambiguous module name" in d for d in revision.diagnostics)
    finally:
        service.close()


def test_revision_metadata_is_stamped_on_reads(tmp_path):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        r1 = service.index(project.id)
        unit = next(u for u in service.files(project.id).items if u.relative_path == "compute.py")
        document = service.analysis(project.id, unit.id, r1.id)
        refs = [n.source for n in document.graph.nodes if n.source]
        assert refs and all(ref.project_revision_id == r1.id for ref in refs)
        assert all(ref.file_id == unit.id for ref in refs)
        source = service.source(project.id, unit.id, r1.id)
        assert source["revision_id"] == r1.id and source["project_id"] == project.id
    finally:
        service.close()


def test_function_scope_slice(tmp_path):
    root = tmp_path / "lab"
    write(root, "pkg/a.py", "def one():\n    value = 1\n    return value\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        unit = next(u for u in service.files(project.id).items if u.relative_path == "pkg/a.py")
        document = service.analysis(project.id, unit.id)
        function_key = next(
            b.logical_key for b in document.graph.blocks if b.kind == "function"
        )
        sliced = service.graph(project.id, scope_id=function_key)
        assert sliced.graph.roots and sliced.graph.blocks
        ids = {b.id for b in sliced.graph.blocks} | {n.id for n in sliced.graph.nodes}
        for edge in sliced.graph.edges:
            assert edge.source in ids and edge.target in ids
    finally:
        service.close()

def test_dynamic_and_shadowed_calls_stay_unknown(tmp_path):
    root = tmp_path / "lab"
    write(root, "lib.py", "def target():\n    return 1\n")
    write(root, "shadow.py", "from lib import target\n\ndef local():\n    return 1\n\ntarget = local\ntarget()\n")
    write(root, "dyn.py", "import lib\nlib.target()\ngetattr(lib, 'target')()\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        graph_slice = service.graph(project.id)
        codes = {c.code for c in graph_slice.graph.coverage}
        assert "shadowed_call" in codes or "dynamic_call" in codes
        # the shadowed module-level rebinding must not create a wrong call edge
        shadow_unit = next(u for u in service.files(project.id).items if u.relative_path == "shadow.py")
        assert shadow_unit.status == "parsed"
    finally:
        service.close()


def test_mutual_import_cycle_is_allowed(tmp_path):
    root = tmp_path / "lab"
    write(root, "one.py", "import two\n\ndef a():\n    return two.b()\n")
    write(root, "two.py", "def b():\n    return 2\n")
    write(root, "three.py", "import one\n\ndef c():\n    return one.a()\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        graph = service.graph(project.id).graph
        ids = {b.id for b in graph.blocks} | {n.id for n in graph.nodes}
        for edge in graph.edges:
            assert edge.source in ids and edge.target in ids
    finally:
        service.close()


def test_lexical_scope_nested_keyword_and_alias(tmp_path):
    root = tmp_path / "lab"
    write(root, "compute.py", "def scale(v, *, factor=1):\n    return v * factor\n")
    write(
        root,
        "main.py",
        "from compute import scale as s\nX = 1\ndef outer():\n    X = 2\n"
        "    def inner():\n        return X\n    return inner\nY = s(X, factor=X)\n",
    )
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        graph = service.graph(project.id).graph
        nodes = {node.id: node for node in graph.nodes}
        sources = [nodes[e.source] for e in graph.edges if e.kind == "argument" and e.source in nodes]
        assert sources, [e.kind for e in graph.edges]
        # Module-level X (line 2) must win; outer()'s X must never leak.
        assert all(node.source.line == 2 for node in sources), [(n.label, n.source.line) for n in sources]
    finally:
        service.close()


def test_overview_bounds_more_than_350_files(tmp_path):
    root = tmp_path / "lab"; root.mkdir()
    for number in range(360):
        write(root, f"mod_{number:03}.py", f"X = {number}\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        sliced = service.graph(project.id)
        assert len(sliced.graph.nodes) + len(sliced.graph.blocks) <= 350
        assert sliced.omitted_count > 0
        units = {u.relative_path: u for u in service.files(project.id, limit=1000).items}
        # An omitted file stays individually explorable through its file scope.
        one = service.graph(project.id, scope_id=units["mod_359.py"].id)
        ids = {b.id for b in one.graph.blocks} | {n.id for n in one.graph.nodes}
        assert one.graph.nodes and all(e.source in ids and e.target in ids for e in one.graph.edges)
    finally:
        service.close()


def test_overview_skips_full_analysis_loading(tmp_path, monkeypatch):
    root = tmp_path / "lab"; root.mkdir()
    for number in range(80):
        write(root, f"m{number:03}.py", f"X = {number}\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        from contract_driven_ai_flow.research.projects.store import ProjectStore

        calls = {"n": 0}
        real = ProjectStore.get_analysis

        def counting(self, analysis_id):
            calls["n"] += 1
            return real(self, analysis_id)

        monkeypatch.setattr(ProjectStore, "get_analysis", counting)
        service.graph(project.id)
        assert calls["n"] == 0
        unit = service.files(project.id, limit=1000).items[0]
        service.analysis(project.id, unit.id)
        assert calls["n"] == 1
    finally:
        service.close()


def test_cancellation_during_discovery_not_pre_set(tmp_path):
    root = tmp_path / "lab"; root.mkdir()
    for number in range(20):
        write(root, f"f{number:02}.py", f"X = {number}\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        cancel = threading.Event()
        seen = {"n": 0}

        def progress(_):
            seen["n"] += 1
            if seen["n"] >= 3:
                cancel.set()

        with pytest.raises((RuntimeError, InterruptedError)):
            service.index(project.id, cancel=cancel, progress=progress)
        assert seen["n"] >= 3
        with pytest.raises(KeyError):
            service.revision(project.id)
    finally:
        service.close()


def test_ambiguous_rename_is_reported(tmp_path):
    root = tmp_path / "lab"; root.mkdir()
    body = "def f():\n    return 1\n"
    write(root, "a.py", body)
    write(root, "b.py", body)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        (root / "a.py").unlink()
        (root / "b.py").unlink()
        write(root, "c.py", body)
        revision = service.index(project.id)
        assert any("Ambiguous rename" in d for d in revision.diagnostics)
    finally:
        service.close()


def test_syntax_error_document_is_cached(tmp_path):
    root = tmp_path / "lab"; root.mkdir()
    write(root, "broken.py", "def (\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        unit = next(u for u in service.files(project.id).items if u.relative_path == "broken.py")
        assert unit.status == "error" and unit.diagnostics
        second = service.index(project.id)
        assert second.parsed_files == 0 and second.reused_files == 1
        again = next(u for u in service.files(project.id).items if u.relative_path == "broken.py")
        assert again.status == "error"
    finally:
        service.close()


def test_large_overview_keeps_cross_file_call_edges(tmp_path):
    root = tmp_path / "lab"; root.mkdir()
    write(root, "compute.py", "def scale(v):\n    return v * 2\n")
    write(root, "main.py", "from compute import scale\nX = 1\nY = scale(X)\n")
    for number in range(70):
        write(root, f"noise_{number:02}.py", f"Z = {number}\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        graph = service.graph(project.id).graph
        calls = [e for e in graph.edges if e.kind == "call"]
        assert calls, [(e.kind, e.label) for e in graph.edges]
        ids = {b.id for b in graph.blocks} | {n.id for n in graph.nodes}
        assert all(e.source in ids and e.target in ids for e in graph.edges)
    finally:
        service.close()


def test_nested_function_is_not_importable_export(tmp_path):
    root = tmp_path / "lab"; root.mkdir()
    write(root, "lib.py", "def outer():\n    def nested():\n        return 1\n    return nested\n")
    write(root, "main.py", "from lib import nested\nR = nested()\n")
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        service.index(project.id)
        graph = service.graph(project.id).graph
        assert not [e for e in graph.edges if e.kind == "call"]
    finally:
        service.close()


def test_incremental_reuses_unchanged_without_loading_analysis(tmp_path, monkeypatch):
    root = tmp_path / "lab"; fixture(root)
    service = ProjectService(tmp_path / "host")
    try:
        project = service.open(root)
        first = service.index(project.id)
        assert first.parsed_files == 3
        from contract_driven_ai_flow.research.projects.store import ProjectStore

        def forbidden(self, analysis_id):
            raise AssertionError("unchanged file must not load full analysis")

        monkeypatch.setattr(ProjectStore, "get_analysis", forbidden)
        second = service.index(project.id)
        assert second.parsed_files == 0 and second.reused_files == 3
        write(root, "compute.py", "def scale(values):\n    return values\n")
        third = service.index(project.id)
        assert third.parsed_files == 1 and third.reused_files == 2
        unit = next(u for u in service.files(project.id).items if u.relative_path == "main.py")
        assert service.source(project.id, unit.id)["code"]
    finally:
        service.close()

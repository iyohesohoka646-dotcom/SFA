from concurrent.futures import ThreadPoolExecutor

import pytest

from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.changes import ScientificChangeService


def project(tmp_path):
    path = tmp_path / 'analysis.py'
    path.write_text('import math\nX = 2\ndef analyze(X):\n    return X + 1\ndef sibling(X):\n    return X * 3\n', encoding='utf-8')
    research = ResearchService(tmp_path)
    analysis = research.workbench.import_source(path)
    obj = next(o for o in analysis.objects if o.qualname == 'analyze')
    return research, path, analysis, obj


def test_inert_scoped_candidate_accept_and_reviewed_rollback(tmp_path):
    research, path, analysis, obj = project(tmp_path)
    try:
        changes = research.workbench.changes
        before = path.read_text()
        proposal = changes.propose(analysis.id, obj.id, 'def analyze(X):\n    return X + 2\n')
        assert proposal.status == 'valid' and proposal.behavior == 'unverified'
        assert path.read_text() == before and research.store.runs() == []
        assert 'sibling' not in proposal.diff
        applied = changes.accept(proposal.id)
        assert applied.status == 'accepted' and 'return X * 3' in path.read_text()
        rollback = changes.rollback(proposal.id)
        assert rollback.status == 'valid' and path.read_text() != before
        changes.accept(rollback.id)
        assert path.read_text() == before
    finally:
        research.close()


@pytest.mark.parametrize('candidate', ['def analyze(y):\n    return y\n', 'def analyze(X):\n    return X\nextra = 1\n', 'def analyze(X):\n    import rogue_dependency\n    return X\n', 'def analyze(X):\n    return __import__("os")\n'])
def test_invalid_signature_top_level_or_nested_import_is_blocked(tmp_path, candidate):
    research, path, analysis, obj = project(tmp_path)
    try:
        before = path.read_bytes()
        proposal = research.workbench.changes.propose(analysis.id, obj.id, candidate)
        assert proposal.status == 'invalid'
        with pytest.raises(ValueError): research.workbench.changes.accept(proposal.id)
        assert path.read_bytes() == before
    finally:
        research.close()


def test_assignment_target_is_stable_and_other_symbols_survive(tmp_path):
    research, path, analysis, obj = project(tmp_path)
    try:
        target = next(o for o in analysis.objects if o.qualname == 'X')
        changes = research.workbench.changes
        invalid = changes.propose(analysis.id, target.id, 'Y = 3\n')
        assert invalid.status == 'invalid'
        proposal = changes.propose(analysis.id, target.id, 'X = math.sqrt(9)\n')
        changes.accept(proposal.id)
        assert 'X = math.sqrt(9)' in path.read_text() and 'def sibling(X)' in path.read_text()
    finally:
        research.close()


def test_concurrent_accepts_and_external_edits_conflict(tmp_path):
    research, path, analysis, obj = project(tmp_path)
    try:
        changes = research.workbench.changes
        first = changes.propose(analysis.id, obj.id, 'def analyze(X):\n    return X + 2\n')
        second = changes.propose(analysis.id, obj.id, 'def analyze(X):\n    return X + 3\n')
        def accept(key):
            try: return changes.accept(key).status
            except ValueError: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(accept, [first.id, second.id]))
        assert sorted(statuses) == ['accepted', 'conflict']
        assert {changes.get(first.id).status, changes.get(second.id).status} == {'accepted', 'conflict'}
        accepted = first if statuses[0] == 'accepted' else second
        path.write_text(path.read_text() + '# another edit\n')
        with pytest.raises(ValueError, match='changed'): changes.rollback(accepted.id)
    finally:
        research.close()


def test_new_analysis_is_project_scoped_and_inert(tmp_path):
    research, path, analysis, obj = project(tmp_path)
    try:
        changes = research.workbench.changes
        proposal = changes.propose_new(analysis.id, 'derived.py', 'import math\nX = math.sqrt(9)\n')
        assert not (tmp_path / 'derived.py').exists()
        changes.accept(proposal.id)
        assert (tmp_path / 'derived.py').exists() and not research.store.runs()
        with pytest.raises(ValueError): changes.propose_new(analysis.id, '../outside.py', 'X = 1\n')
    finally:
        research.close()


def test_behavior_cannot_be_verified_by_a_model_or_unrelated_run(tmp_path):
    research, path, analysis, obj = project(tmp_path)
    try:
        changes = research.workbench.changes
        proposal = changes.propose(analysis.id, obj.id, 'def analyze(X):\n    return X + 2\n')
        changes.accept(proposal.id)
        with pytest.raises(ValueError): changes.record_validation(proposal.id, 'not-a-run', [])
        assert changes.get(proposal.id).behavior == 'unverified'
    finally:
        research.close()

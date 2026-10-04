"""Historical analysis lookup does not load unrelated stored semantic graphs."""

import json
import sys

import pytest

from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.store import WorkbenchStore


def test_store_analysis_lookup_is_exact_and_returns_the_latest_matching_id(tmp_path):
    store = WorkbenchStore(tmp_path)
    path = "analysis 'quoted'.py"
    for identifier, digest, source_path, created in [
        ('old', 'digest', path, 1), ('latest', 'digest', path, 3),
        ('same-time-last', 'digest', path, 3), ('other-path', 'digest', 'other.py', 9),
        ('other-digest', 'different', path, 10),
    ]:
        store.put('analyses', identifier, {'id': identifier, 'source_digest': digest, 'path': source_path})
        with store.connect() as conn:
            conn.execute("UPDATE records SET created=? WHERE kind='analyses' AND id=?", (created, identifier))
    assert store.find_analysis_id(source_digest='digest', path=path) == 'same-time-last'
    assert store.find_analysis_id(source_digest='missing', path=path) is None
    assert store.find_analysis_id(source_digest='digest', path='missing.py') is None


def test_run_analysis_finds_old_saved_identity_beyond_list_limit_without_loading_unrelated_graphs(tmp_path, monkeypatch):
    path = tmp_path / "analysis 'quoted'.py"
    path.write_text('X = 1\nY = X + 1\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        workbench = research.workbench
        original = workbench.import_source(path)
        run = research.store.create_run(original.path, interpreter=sys.executable, source_digest=original.source_digest)
        unrelated = original.model_dump(mode='json')
        unrelated['source_digest'] = 'unrelated-digest'
        unrelated['path'] = str(tmp_path / 'unrelated.py')
        # The records contain real semantic graphs; their payloads never need
        # Python deserialization to identify the historical source.
        with workbench.store.connect() as conn:
            conn.executemany('INSERT INTO records(kind,id,payload) VALUES(?,?,?)', [
                ('analyses', f'unrelated-{i}', json.dumps({**unrelated, 'id': f'unrelated-{i}'})) for i in range(1050)
            ])
        path.write_text('CURRENT = 8\n', encoding='utf-8')

        def no_record_scan(*args, **kwargs):
            raise AssertionError('Historical graph lookup must not deserialize the analysis list')

        monkeypatch.setattr(workbench.store, 'list', no_record_scan)
        historical = workbench.run_analysis(run['id'])
        assert historical.id == original.id
        assert historical.model_dump() == original.model_dump()


@pytest.mark.parametrize('mismatch', ['path', 'digest'])
def test_run_analysis_uses_archived_evidence_when_saved_identity_does_not_match(tmp_path, mismatch):
    path = tmp_path / 'analysis.py'
    path.write_bytes(b'X = 1\r\nY = X + 1\r\n')
    with ResearchService(tmp_path) as research:
        workbench = research.workbench
        original = workbench.import_source(path)
        run = research.store.create_run(original.path, interpreter=sys.executable, source_digest=original.source_digest)
        workbench.store.delete('analyses', original.id)
        unrelated = original.model_copy(update={
            'id': 'nonmatching-saved-identity',
            'path': str(tmp_path / 'another.py') if mismatch == 'path' else original.path,
            'source_digest': 'different-digest' if mismatch == 'digest' else original.source_digest,
        })
        workbench.store.put('analyses', unrelated.id, unrelated)
        path.unlink()
        historical = workbench.run_analysis(run['id'])
        assert historical.id not in (original.id, unrelated.id)
        assert historical.path == original.path and historical.source_digest == original.source_digest
        assert {obj.name for obj in historical.objects} == {'X', 'Y'}
        assert {obj.id for obj in historical.objects} == {obj.id for obj in original.objects}
        assert workbench.analysis_source(historical.id)['code'] == 'X = 1\r\nY = X + 1\r\n'
        assert workbench.run_analysis(run['id']).id == historical.id

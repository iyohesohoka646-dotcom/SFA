"""Formatting is a reviewed source change, never a scientific rewrite."""

import asyncio
import json

import httpx
import pytest

from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.source_format import verify_format
from contract_driven_ai_flow.research.workbench.intelligence.harness import HarnessRequest, HarnessService
from contract_driven_ai_flow.research.workbench.models import HarnessPolicy
from contract_driven_ai_flow.settings.models import ProviderProfile
from contract_driven_ai_flow.settings.service import ModelSettingsService


SOURCE = '# 保留研究说明\nimport math\nX=2\ndef analyze(X):\n    Z=X+1\n    return Z\n'
FORMATTED = '# 保留研究说明\nimport math\n\nX = 2\n\n\ndef analyze(X):\n    Z = X + 1\n    return Z\n'


def project(tmp_path, source=SOURCE):
    path = tmp_path / 'analysis.py'
    path.write_text(source, encoding='utf-8')
    research = ResearchService(tmp_path)
    return research, path, research.workbench.import_source(path)


def test_format_preview_accept_and_rollback_preserve_computation(tmp_path):
    research, path, analysis = project(tmp_path)
    try:
        changes = research.workbench.changes
        proposal = changes.propose_format(analysis.id, FORMATTED)
        assert proposal.operation == 'format' and proposal.status == 'valid'
        assert proposal.behavior == 'unverified'
        assert path.read_text(encoding='utf-8') == SOURCE
        assert research.store.runs() == []
        changes.accept(proposal.id)
        assert path.read_text(encoding='utf-8') == FORMATTED
        rollback = changes.rollback(proposal.id)
        assert rollback.operation == 'format' and rollback.status == 'valid'
        changes.accept(rollback.id)
        assert path.read_text(encoding='utf-8') == SOURCE
        assert research.store.runs() == []
    finally:
        research.close()


def test_format_type_ignore_remains_attached_to_original_statement():
    original = 'x: int = "s"  # type: ignore[assignment]\ny: int = "s"\n'
    moved = 'x: int = "s"\ny: int = "s"  # type: ignore[assignment]\n'
    with pytest.raises(ValueError):
        verify_format(original, moved)
    verify_format(original, '\n\nx: int = "s"  # type: ignore[assignment]\n\ny: int = "s"\n')


def test_format_rejects_candidate_that_cannot_use_original_encoding(tmp_path):
    original = '# coding: ascii\nx = "\\u03b1"\n'
    research, path, analysis = project(tmp_path, original)
    try:
        before = path.read_bytes()
        proposal = research.workbench.changes.propose_format(analysis.id, '# coding: ascii\nx = "α"\n')
        assert proposal.status == 'invalid'
        assert path.read_bytes() == before
    finally:
        research.close()


@pytest.mark.parametrize('candidate', [
    FORMATTED.replace('X + 1', 'X + 2'),
    FORMATTED.replace('import math', 'import math\nimport os'),
    FORMATTED.replace('def analyze(X)', 'def analyze(Y)'),
    FORMATTED.replace('# 保留研究说明', '# 模型替换了研究说明'),
    FORMATTED + '\nprint(analyze(X))\n',
])
def test_format_rejects_semantic_or_comment_changes(tmp_path, candidate):
    research, path, analysis = project(tmp_path)
    try:
        before = path.read_bytes()
        proposal = research.workbench.changes.propose_format(analysis.id, candidate)
        assert proposal.status == 'invalid'
        with pytest.raises(ValueError):
            research.workbench.changes.accept(proposal.id)
        assert path.read_bytes() == before
    finally:
        research.close()


def test_format_stale_source_blocks_acceptance(tmp_path):
    research, path, analysis = project(tmp_path)
    try:
        proposal = research.workbench.changes.propose_format(analysis.id, FORMATTED)
        path.write_text(SOURCE + '# 新的修改\n', encoding='utf-8')
        with pytest.raises(ValueError, match='changed'):
            research.workbench.changes.accept(proposal.id)
        assert research.workbench.changes.get(proposal.id).status == 'conflict'
        assert '# 新的修改' in path.read_text(encoding='utf-8')
    finally:
        research.close()


def test_configured_model_can_only_stage_formatting_and_real_receipt(tmp_path):
    research, path, analysis = project(tmp_path)
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            action = {'tool': 'source.read_file', 'arguments': {}}
        elif len(calls) == 2:
            received = json.loads(body['messages'][-1]['content'].split('\n', 1)[1])['result']['code']
            assert received.replace('\r\n', '\n') == SOURCE
            action = {'tool': 'code.propose_format', 'arguments': {'candidate': FORMATTED}}
        else:
            receipt = json.loads(body['messages'][-1]['content'].split('\n', 1)[1])
            action = {'answer': '已生成保留计算内容的整理提案。', 'citations': [receipt['reference']]}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(action)}}]})
    models = ModelSettingsService(tmp_path, transport=httpx.MockTransport(respond))
    models.save(ProviderProfile(id='format-fixture', protocol='openai-compatible', base_url='https://fixture.invalid/v1', models=['research'], default_model='research'))
    harness = HarnessService(research.workbench, models)
    try:
        request = HarnessRequest(question='整理间距与分段', analysis_id=analysis.id, purpose='format_source', policy=HarnessPolicy(role='code', provider_id='format-fixture', model='research'))
        result = asyncio.run(harness.execute(request))
        assert result['status'] == 'completed', result['message']
        proposals = research.workbench.store.list('proposals')
        assert len(proposals) == 1 and proposals[0]['operation'] == 'format' and proposals[0]['status'] == 'valid'
        assert path.read_text(encoding='utf-8') == SOURCE and research.store.runs() == []
        advertised = {t['name'] for t in harness.tools.describe(request)}
        assert 'source.read_file' in advertised and 'code.propose_format' in advertised
        assert 'code.propose' not in advertised and 'plan.execute' not in advertised
        generic = request.model_copy(update={'purpose': 'general'})
        assert 'source.read_file' not in {t['name'] for t in harness.tools.describe(generic)}
        with pytest.raises(ValueError, match='scope'):
            focused = request.model_copy(update={'object_id': analysis.objects[-1].id})
            harness.tools.call('source.read_file', {}, focused)
    finally:
        models.close()
        research.close()


def test_secret_source_never_enters_format_model_context(tmp_path):
    research, path, analysis = project(tmp_path, 'api_key = "never-send-this-secret"\nX=2\n')
    models = ModelSettingsService(tmp_path)
    harness = HarnessService(research.workbench, models)
    try:
        request = HarnessRequest(question='整理', analysis_id=analysis.id, purpose='format_source', policy=HarnessPolicy(role='code'))
        with pytest.raises(ValueError, match='secret'):
            harness.tools.call('source.read_file', {}, request)
        assert 'never-send-this-secret' not in json.dumps(research.workbench.store.list('contexts'))
    finally:
        models.close()
        research.close()

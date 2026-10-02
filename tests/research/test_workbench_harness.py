import asyncio
import json
import threading

import httpx
import pytest

from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.models import HarnessPolicy
from contract_driven_ai_flow.research.workbench.intelligence.harness import HarnessService, HarnessRequest
from contract_driven_ai_flow.research.workbench.intelligence.context import HarnessContextBuilder
from contract_driven_ai_flow.settings.models import ProviderProfile
from contract_driven_ai_flow.settings.service import ModelSettingsService


def setup(tmp_path, respond):
    path = tmp_path / 'analysis.py'
    path.write_text('api_key = "never-send-this-secret"\ndef analyze(X):\n    Z = X + 1\n    return Z\ndef sibling():\n    marker = "SIBLING_PRIVATE_BODY"\n    return marker\n', encoding='utf-8')
    research = ResearchService(tmp_path)
    wb = research.workbench
    analysis = wb.import_source(path)
    obj = next(o for o in analysis.objects if o.qualname == 'analyze')
    calls = []
    def handler(request):
        body = json.loads(request.content); calls.append(body)
        text = respond(body, len(calls), obj)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(text)}}], 'usage': {'prompt_tokens': 12, 'completion_tokens': 10}})
    models = ModelSettingsService(tmp_path, transport=httpx.MockTransport(handler))
    models.save(ProviderProfile(id='test', protocol='openai-compatible', base_url='https://fixture.invalid/v1', default_model='model', models=['model']))
    harness = HarnessService(wb, models)
    request = HarnessRequest(question='解释这一步计算', analysis_id=analysis.id, object_id=obj.id,
        policy=HarnessPolicy(provider_id='test', model='model'))
    return research, harness, request, calls, obj


def test_model_uses_registered_tool_and_real_scoped_result(tmp_path):
    def respond(body, call, obj):
        if call == 1:
            return {'tool': 'source.read', 'arguments': {'object_id': obj.id}}
        assert 'return Z' in body['messages'][-1]['content']
        return {'answer': 'Z 是 X 加一的结果。', 'citations': ['source:' + obj.id]}
    research, harness, request, calls, obj = setup(tmp_path, respond)
    try:
        result = asyncio.run(harness.execute(request, task_id='task', cancel=threading.Event()))
        assert result['status'] == 'completed' and len(calls) == 2
        assert result['citations'] == ['source:' + obj.id]
        assert calls[0]['max_tokens'] == request.policy.output_tokens
        context = harness.workbench.store.get('contexts', result['context_id'])
        encoded = json.dumps(context)
        assert 'environment' in calls[0]['messages'][0]['content'] and 'source.read' in encoded
        assert 'SIBLING_PRIVATE_BODY' not in encoded and 'never-send-this-secret' not in encoded
        assert context['calls'][0]['messages'] == calls[0]['messages']
    finally:
        research.close()


@pytest.mark.parametrize('tool,arguments', [('shell.run', {'command': 'anything'}), ('source.read', {'object_id': 'wrong-id'}), ('plan.execute', {'plan_id': 'unknown'})])
def test_unknown_tools_and_scope_cannot_expand_permissions(tmp_path, tool, arguments):
    research, harness, request, calls, obj = setup(tmp_path, lambda *_: {'tool': tool, 'arguments': arguments})
    try:
        result = asyncio.run(harness.execute(request, task_id='task', cancel=threading.Event()))
        assert result['status'] == 'error' and len(calls) == 1
        assert not research.store.runs()
    finally:
        research.close()


def test_stale_source_and_budget_block_calls(tmp_path):
    research, harness, request, calls, obj = setup(tmp_path, lambda *_: {'answer': 'x', 'citations': []})
    try:
        Path = __import__('pathlib').Path
        Path(harness.workbench.analysis(request.analysis_id).path).write_text('X = 9\n')
        result = asyncio.run(harness.execute(request, task_id='task', cancel=threading.Event()))
        assert result['status'] == 'error' and calls == []
    finally:
        research.close()
    other = tmp_path / 'budget'; other.mkdir()
    research, harness, request, calls, obj = setup(other, lambda _, n, o: {'tool': 'source.read', 'arguments': {'object_id': o.id}})
    try:
        request.policy.max_calls = 1
        result = asyncio.run(harness.execute(request, task_id='task', cancel=threading.Event()))
        assert result['status'] == 'budget_exhausted' and len(calls) == 1
        request.policy.input_tokens = 512
        result = asyncio.run(harness.execute(request.model_copy(update={'question': '长' * 10000}), task_id='large', cancel=threading.Event()))
        assert result['status'] == 'budget_exhausted' and len(calls) == 1
    finally:
        research.close()


def test_cancelled_request_records_no_invented_answer(tmp_path):
    research, harness, request, calls, obj = setup(tmp_path, lambda *_: {'answer': 'x', 'citations': []})
    cancel = threading.Event(); cancel.set()
    try:
        result = asyncio.run(harness.execute(request, task_id='task', cancel=cancel))
        assert result['status'] == 'cancelled' and calls == []
    finally:
        research.close()


def test_skill_and_manual_results_do_not_become_program_checks(tmp_path):
    def respond(_, call, obj):
        return {'tool': 'source.read', 'arguments': {'object_id': obj.id}} if call == 1 else {'answer': '需要复核', 'citations': ['source:' + obj.id]}
    research, harness, request, calls, obj = setup(tmp_path, respond)
    try:
        path = tmp_path / 'SKILL.md'; path.write_text('# 检查\n检查数值，不能假设没有缺失值。\n')
        skill = harness.skills.register(path)
        request.skill_id = skill['id']
        result = asyncio.run(harness.execute(request, task_id='task', cancel=threading.Event()))
        assert result['provenance'] == 'skill' and result['status'] == 'completed'
        output = harness.manual(instance_id='review', analysis_id=request.analysis_id, note='图看过了', verdict='pass')
        assert output.execution == 'manual' and output.provenance == 'manual'
        assert output.data['automatic_check'] is False
    finally:
        research.close()


def test_context_keeps_exact_large_messages(tmp_path):
    research, harness, request, calls, obj = setup(tmp_path, lambda *_: {'answer': 'x', 'citations': []})
    request.question = 'a' * 18000
    request.policy.input_tokens = 40000
    try:
        result = asyncio.run(harness.execute(request, task_id='large', cancel=threading.Event()))
        assert result['status'] == 'completed'
        assert harness.workbench.store.get('contexts', result['context_id'])['calls'][0]['messages'] == calls[0]['messages']
    finally:
        research.close()


def test_cancellation_during_inference_reaches_the_provider_call(tmp_path):
    research, harness, request, calls, obj = setup(tmp_path, lambda *_: {'answer': 'x', 'citations': []})
    cancel = threading.Event()
    async def handler(_):
        asyncio.get_running_loop().call_later(.02, cancel.set)
        await asyncio.sleep(10)
        return httpx.Response(200)
    harness.models.transport = httpx.MockTransport(handler)
    try:
        result = asyncio.run(harness.execute(request, task_id='slow', cancel=cancel))
        assert result['status'] == 'cancelled' and result['answer'] == ''
        assert result['requests'] == 1
    finally:
        research.close()

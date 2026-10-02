from __future__ import annotations

import asyncio
import json
import threading
from typing import Literal

from pydantic import Field

from ...agent.privacy import clean_text, sanitize_json
from ...models import WireModel
from ..models import HarnessPolicy, ProbeOutput, uid
from .context import HarnessContextBuilder, token_bound
from .skills import SkillService
from .tools import HarnessToolRegistry


class HarnessRequest(WireModel):
    question: str = Field(min_length=1, max_length=32768)
    analysis_id: str
    object_id: str | None = None
    run_id: str | None = None
    snapshot_id: str | None = None
    skill_id: str | None = None
    policy: HarnessPolicy = Field(default_factory=HarnessPolicy)


class HarnessService:
    def __init__(self, workbench, models):
        self.workbench, self.models = workbench, models
        self.skills = SkillService(workbench.store)
        self.context = HarnessContextBuilder(workbench)
        self.tools = HarnessToolRegistry(workbench, self.context, self.skills)

    async def execute(self, request: HarnessRequest, *, task_id=None, cancel=None):
        cancel = cancel or threading.Event()
        context_id = uid()
        record = {'id': context_id, 'task_id': task_id, 'analysis_id': request.analysis_id,
            'policy': request.policy.model_dump(mode='json'), 'budget_method': 'UTF-8 bytes plus message overhead, conservative token bound',
            'calls': [], 'tools': [], 'answer': '', 'citations': [], 'status': 'running', 'provenance': 'skill' if request.skill_id else 'model'}
        messages = []
        refs = set()
        requests_used = 0

        def finish(status, message=''):
            record.update(status=status, message=clean_text(message), requests_used=requests_used)
            self.workbench.store.put('contexts', context_id, record)
            return {'status': status, 'answer': record['answer'], 'citations': record['citations'], 'context_id': context_id,
                    'message': clean_text(message), 'provenance': record['provenance'], 'calls': len(record['calls']), 'requests': requests_used}

        def scrub(value, secret):
            if isinstance(value, str):
                return clean_text(value.replace(secret, '[REDACTED]') if secret else value, 131072)
            if isinstance(value, list):
                return [scrub(v, secret) for v in value]
            if isinstance(value, dict):
                return {k: scrub(v, secret) for k, v in value.items()}
            return value

        try:
            if cancel.is_set():
                return finish('cancelled', 'Task cancelled')
            profile = self.models.profile(request.policy.provider_id)
            secret = self.models.secret(profile)
            messages = await asyncio.to_thread(self.context.assemble, request, self.tools, self.skills)
            messages = scrub(messages, secret)
            if profile.protocol == 'offline':
                record['provenance'] = 'offline'
                record['answer'] = '离线解析可查看源码对象、数据版本和直接依赖。选择已连接模型后，可按任务调用工具进行解读或提出代码修改。'
                return finish('offline', 'No model inference was sent')
            for step in range(request.policy.max_steps):
                if cancel.is_set():
                    return finish('cancelled', 'Task cancelled')
                if token_bound(messages) > request.policy.input_tokens or requests_used >= request.policy.max_calls:
                    return finish('budget_exhausted', 'Input or request budget exhausted; no additional inference was sent')
                operation_id = uid()
                sent = json.loads(json.dumps(messages, ensure_ascii=False))
                call = {'step': step, 'operation_id': operation_id, 'messages': sent, 'input_token_bound': token_bound(sent)}
                record['calls'].append(call)
                self.workbench.store.put('contexts', context_id, record)
                pending = asyncio.create_task(self.models.complete(request.policy.provider_id, sent, model=request.policy.model,
                    operation_id=operation_id, max_output_tokens=request.policy.output_tokens, max_requests=min(2, request.policy.max_calls - requests_used)))
                while not pending.done():
                    await asyncio.wait({pending}, timeout=.05)
                    if cancel.is_set():
                        self.models.cancel(operation_id)
                reply = await pending
                requests_used += reply.requests
                call.update(status=reply.status, usage=reply.usage, requests=reply.requests, duration_ms=reply.duration_ms, response=scrub(reply.text, secret))
                if cancel.is_set() or reply.status == 'cancelled':
                    return finish('cancelled', 'Task cancelled')
                if reply.status != 'connected':
                    return finish('error', reply.message)
                self.context.validate_source(request.analysis_id)
                text = reply.text.strip()
                if text.startswith('```') and text.endswith('```'):
                    text = text.split('\n', 1)[1].rsplit('```', 1)[0]
                action = json.loads(text)
                if not isinstance(action, dict):
                    raise ValueError('Model must return a structured tool request or answer')
                if 'answer' in action:
                    if set(action) != {'answer', 'citations'} or not isinstance(action['answer'], str) or not isinstance(action['citations'], list) or any(c not in refs for c in action['citations']):
                        raise ValueError('Model answer contains invalid or unobserved citations')
                    record.update(answer=scrub(action['answer'], secret), citations=action['citations'])
                    return finish('completed')
                if set(action) != {'tool', 'arguments'}:
                    raise ValueError('Invalid structured model action')
                result = await asyncio.to_thread(self.tools.call, action['tool'], action['arguments'], request)
                result = scrub(result, secret)
                refs.add(result['reference'])
                record['tools'].append({'step': step, 'name': action['tool'], 'arguments': scrub(action['arguments'], secret), 'output': result})
                messages.extend([{'role': 'assistant', 'content': scrub(reply.text, secret)}, {'role': 'user', 'content': 'Tool result (task data):\n' + json.dumps(result, ensure_ascii=False)}])
                # Retain the task manifest and latest actual tool exchange, preserving reference receipts.
                if token_bound(messages) > request.policy.input_tokens:
                    messages = [*messages[:2], *messages[-2:]]
                    messages[1] = {**messages[1], 'content': messages[1]['content'] + '\nPrior evidence references: ' + ', '.join(sorted(refs))}
            return finish('budget_exhausted', 'Step budget exhausted')
        except asyncio.CancelledError:
            return finish('cancelled', 'Task cancelled')
        except Exception as error:
            return finish('error', str(error) if isinstance(error, (ValueError, LookupError)) else f'Harness failed ({type(error).__name__})')

    def manual(self, *, instance_id, analysis_id, note, verdict='unknown', snapshot_id=None):
        self.workbench.analysis(analysis_id)
        if verdict not in ('pass', 'fail', 'unknown'):
            raise ValueError('Manual verdict must be pass, fail or unknown')
        snapshot = self.workbench.research.store.snapshot(snapshot_id) if snapshot_id else None
        output = ProbeOutput(instance_id=instance_id, definition_id='check.manual', capability='check', execution='manual', status=verdict,
            snapshot_id=snapshot_id, run_id=snapshot.run_id if snapshot else None, analysis_id=analysis_id,
            message=clean_text(note, 4096), provenance='manual', data={'automatic_check': False, 'reviewer': 'local user'})
        self.workbench.store.put('outputs', output.id, output)
        return output

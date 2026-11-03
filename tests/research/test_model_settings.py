import asyncio
import json

import httpx
import pytest
from typer.testing import CliRunner


class MemoryCredentials:
    def __init__(self, available=True):
        self.values = {}
        self.available = available

    def put(self, reference, secret):
        if not self.available:
            raise RuntimeError("System credential store is unavailable")
        self.values[reference] = secret

    def get(self, reference):
        return self.values.get(reference)


def profile(**kwargs):
    from contract_driven_ai_flow.settings.models import ProviderProfile
    return ProviderProfile(id="lab", protocol="openai-compatible", base_url="https://models.example/v1",
                           models=["model-a"], default_model="model-a", **kwargs)


def test_model_profiles_are_shared_without_secret_readback_or_plaintext(tmp_path):
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    from contract_driven_ai_flow.cli import app
    settings = ModelSettingsService(tmp_path, credentials=MemoryCredentials())
    public = settings.save(profile(), secret="synthetic-settings-secret")
    assert public.configured and public.credential_ref.startswith("keyring:")
    assert "synthetic-settings-secret" not in public.model_dump_json()
    assert "synthetic-settings-secret" not in json.dumps([p.model_dump(mode="json") for p in settings.list()])
    for path in (tmp_path / ".cdaf").rglob("*"):
        if path.is_file():
            assert b"synthetic-settings-secret" not in path.read_bytes()
    result = CliRunner().invoke(app, ["models", "list", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert next(p for p in json.loads(result.output) if p["id"] == "lab")["default_model"] == "model-a"


def test_missing_system_vault_never_falls_back_to_a_plaintext_file(tmp_path):
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    settings = ModelSettingsService(tmp_path, credentials=MemoryCredentials(False))
    with pytest.raises(ValueError, match="credential"):
        settings.save(profile(), secret="synthetic-unavailable-secret")
    assert not any(p.id == "lab" for p in settings.list())
    assert all(b"synthetic-unavailable-secret" not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


def test_environment_references_and_connection_discovery_use_selected_protocol(tmp_path, monkeypatch):
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    monkeypatch.setenv("CDAF_TEST_MODEL_KEY", "synthetic-env-key")
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-env-key"
        return httpx.Response(200, json={"data": [{"id": "model-b"}, {"id": "model-a"}]})
    settings = ModelSettingsService(tmp_path, credentials=MemoryCredentials(), transport=httpx.MockTransport(handler))
    settings.save(profile(credential_ref="env:CDAF_TEST_MODEL_KEY"))
    result = asyncio.run(settings.test("lab"))
    assert result.status == "connected" and result.inference is False
    assert result.models == ["model-a", "model-b"]
    assert len(requests) == 1 and requests[0].method == "GET" and requests[0].url.path == "/v1/models"


def test_anthropic_inference_and_usage_are_explicit_and_bounded(tmp_path):
    from contract_driven_ai_flow.settings.models import ProviderProfile
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    def handler(request):
        assert request.headers["x-api-key"] == "synthetic-anthropic"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body=json.loads(request.content)
        assert body["model"] == "manual-model" and body["max_tokens"] <= 2048
        return httpx.Response(200, json={"content":[{"type":"text","text":"OK"}],"usage":{"input_tokens":12,"output_tokens":1}})
    settings=ModelSettingsService(tmp_path,credentials=MemoryCredentials(),transport=httpx.MockTransport(handler))
    settings.save(ProviderProfile(id="anthropic",protocol="anthropic",base_url="https://models.example/v1",default_model="manual-model"),secret="synthetic-anthropic")
    result=asyncio.run(settings.test("anthropic",inference=True))
    assert result.status=="connected" and result.inference
    assert result.usage["input_tokens"]==12


def test_slow_connection_can_be_cancelled_and_error_bodies_are_not_returned(tmp_path):
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    started=asyncio.Event()
    async def handler(request):
        started.set()
        await asyncio.Event().wait()
    settings=ModelSettingsService(tmp_path,credentials=MemoryCredentials(),transport=httpx.MockTransport(handler))
    settings.save(profile())
    async def scenario():
        operation=asyncio.create_task(settings.test("lab",operation_id="cancel-me"))
        await started.wait()
        assert settings.cancel("cancel-me")
        assert (await operation).status=="cancelled"
        assert not settings.cancel("cancel-me")
    asyncio.run(scenario())
    settings.transport=httpx.MockTransport(lambda _:httpx.Response(401,json={"message":"synthetic-server-secret"}))
    result=asyncio.run(settings.test("lab"))
    assert result.status=="error" and "synthetic-server-secret" not in result.model_dump_json()


def test_provider_urls_do_not_store_url_credentials_or_send_keys_over_remote_http():
    from contract_driven_ai_flow.settings.models import ProviderProfile
    for url in ("https://user:private@models.example/v1","https://models.example/v1?api_key=private","http://models.example/v1"):
        with pytest.raises(ValueError):
            ProviderProfile(id="bad",protocol="openai-compatible",base_url=url)
    assert ProviderProfile(id="local",protocol="openai-compatible",base_url="http://127.0.0.1:8080/v1").base_url


@pytest.mark.parametrize('change', ['edit', 'delete'])
def test_late_model_discovery_preserves_concurrent_edits_and_deletions(tmp_path, change):
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    started, release = asyncio.Event(), asyncio.Event()
    async def handler(request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={'data': [{'id': 'discovered'}]})
    settings = ModelSettingsService(tmp_path, credentials=MemoryCredentials(), transport=httpx.MockTransport(handler))
    settings.save(profile())
    async def scenario():
        pending = asyncio.create_task(settings.test('lab'))
        await started.wait()
        if change == 'edit':
            settings.save(settings.profile('lab').model_copy(update={'default_model': 'edited-model'}))
        else:
            settings.delete('lab')
        release.set()
        assert (await pending).status == 'connected'
    asyncio.run(scenario())
    if change == 'edit':
        assert settings.profile('lab').default_model == 'edited-model'
    else:
        assert not any(p.id == 'lab' for p in settings.list())


def test_invalid_cli_model_url_does_not_echo_embedded_credentials(tmp_path):
    from contract_driven_ai_flow.cli import app
    result = CliRunner().invoke(app, ['models', 'configure', 'bad', '--base-url',
        'https://user:synthetic-cli-secret@models.example/v1', '--project', str(tmp_path)])
    assert result.exit_code != 0
    assert 'synthetic-cli-secret' not in result.output


def test_model_api_requires_session_and_never_echoes_secrets(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from contract_driven_ai_flow.research.routes import create_research_app
    from contract_driven_ai_flow.settings import service as model_service
    monkeypatch.setattr(model_service, 'SystemCredentials', MemoryCredentials)
    with TestClient(create_research_app(tmp_path, token='session')) as client:
        headers = {'Authorization': 'Bearer session'}
        assert client.get('/api/v1/settings/models').status_code == 401
        saved = client.put('/api/v1/settings/models/lab', headers=headers,
            json={'profile': profile().model_dump(), 'secret': 'synthetic-api-key'})
        assert saved.status_code == 200 and saved.json()['configured']
        assert 'synthetic-api-key' not in saved.text
        invalid = client.put('/api/v1/settings/models/bad', headers=headers,
            json={'profile': {'id': 'bad!!', 'protocol': 'openai-compatible',
            'base_url': 'https://user:synthetic-invalid-secret@models.example/v1'}, 'secret': 'synthetic-invalid-secret'})
        assert invalid.status_code == 422 and 'synthetic-invalid-secret' not in invalid.text
        assert client.delete('/api/v1/settings/models/offline', headers=headers).status_code == 400

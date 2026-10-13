from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr

from ..research.models import WireModel
from .explanations import ExplanationService
from .models import ProviderProfile
from .service import ModelSettingsService


class SaveProfile(WireModel):
    profile: ProviderProfile
    secret: SecretStr | None = None


class TestProfile(WireModel):
    inference: bool = False
    model: str | None = Field(default=None, max_length=256)
    operation_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]{1,128}$")


class ExplainRequest(WireModel):
    provider_id: str = Field(default="offline", max_length=64)
    model: str = Field(default="rules", max_length=256)
    include_sample: bool = False
    operation_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]{1,128}$")


def attach_model_routes(app, research, settings=None):
    service = settings or getattr(app.state, "models", None) or ModelSettingsService(research.root)
    app.state.models = service
    router = APIRouter(prefix="/api/v1/settings")

    @router.get("/models")
    def profiles():
        return service.list()

    @router.get("/credential-store")
    def credential_store():
        if hasattr(service.credentials, "available"):
            available = bool(service.credentials.available)
        else:
            try:
                service.credentials._backend()
                available = True
            except Exception:
                available = False
        return {"available": available, "plaintext_fallback": False}

    @router.put("/models/{identifier}")
    def save(identifier: str, body: SaveProfile):
        if body.profile.id != identifier:
            raise HTTPException(400, "Model profile ID does not match the request")
        try:
            return service.save(body.profile, secret=body.secret.get_secret_value() if body.secret is not None else None)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.delete("/models/{identifier}")
    def delete(identifier: str):
        service.delete(identifier)
        return {"deleted": identifier}

    async def guard_disconnect(request, operation):
        from ..application.request import await_connected
        return await await_connected(request,operation)

    @router.post("/models/{identifier}/test")
    async def test(identifier: str, body: TestProfile, request: Request):
        return await guard_disconnect(request, asyncio.create_task(service.test(identifier, inference=body.inference, model=body.model, operation_id=body.operation_id)))

    @router.post("/operations/{identifier}/cancel")
    async def cancel(identifier: str):
        return {"cancelled": service.cancel(identifier), "operation_id": identifier}

    app.include_router(router)
    explanations = ExplanationService(research, service)

    @app.post("/api/v1/research/operations/{identifier}/explain")
    async def explain(identifier: str, body: ExplainRequest, request: Request):
        try:
            return await guard_disconnect(request, asyncio.create_task(explanations.explain(identifier,
                provider_id=body.provider_id, model=body.model, include_sample=body.include_sample, operation_token=body.operation_id)))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/v1/research/operations/{identifier}/explanation-context")
    def context(identifier: str, include_sample: bool = False):
        return explanations.context(identifier, include_sample=include_sample)

    previous_validation = app.exception_handlers.get(RequestValidationError)
    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path.startswith("/api/v1/settings"):
            return JSONResponse({"detail": "Invalid model settings; check the fields", "fields": [{"path": list(e["loc"]), "type": e["type"]} for e in error.errors()]}, status_code=422)
        if previous_validation:
            return await previous_validation(request, error)
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

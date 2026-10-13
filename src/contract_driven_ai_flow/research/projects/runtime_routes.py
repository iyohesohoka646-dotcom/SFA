"""Host-machine runtime reference API (sanitized, never returns private values).

Mounted once by the project gateway. Profiles are machine-scoped like model
settings, not an ambient current project; every write is optimistic against the
machine revision and serialised under the in-process host lock.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import local_runtime
from .runtime_models import (
    EnvironmentReferenceRequest,
    InterpreterReferenceRequest,
    RuntimeReferenceState,
)

DEFAULT_RUNTIME_PREFIX = "/api/v1/research/runtime"


def attach_runtime_routes(app, application, *, prefix=DEFAULT_RUNTIME_PREFIX):
    host_root = application.host_root
    router = APIRouter(prefix=prefix)

    def _state() -> RuntimeReferenceState:
        return RuntimeReferenceState.model_validate(
            local_runtime.runtime_state(host_root)
        )

    def _write(action):
        try:
            return action()
        except local_runtime.RuntimeConflict as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(422, str(error))

    @router.get("", response_model=RuntimeReferenceState)
    def runtime_state():
        return _state()

    @router.put("/interpreters/{reference}", response_model=RuntimeReferenceState)
    def put_interpreter(reference: str, body: InterpreterReferenceRequest):
        return _write(
            lambda: local_runtime.set_interpreter_reference(
                host_root, reference, body.path, body.expected_revision
            )
        )

    @router.put("/environments/{reference}", response_model=RuntimeReferenceState)
    def put_environment(reference: str, body: EnvironmentReferenceRequest):
        return _write(
            lambda: local_runtime.set_environment_reference(
                host_root, reference, body.values, body.expected_revision
            )
        )

    app.include_router(router)
    return router

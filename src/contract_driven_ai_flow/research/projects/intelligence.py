"""P4 project intelligence: a task-scoped, bounded interpretation service.

One request is always bound to an immutable (project_id, revision_id). Each
``execute`` builds its own context builder, tool registry and receipts, so
concurrent A/B tasks never share a mutable active request or context. Models are
the shared, caller-owned workbench settings; this service never creates or closes
them.
"""

from __future__ import annotations

import asyncio

from ..workbench.intelligence.harness import HarnessService
from ..workbench.intelligence.skills import SkillService
from .ai_tools import ProjectToolRegistry
from .changes import ProjectChangeService
from .context import ProjectContextBuilder

__all__ = ["ProjectIntelligenceService"]

_FAILED = ("error", "conflict", "budget_exhausted")


class ProjectIntelligenceService:
    def __init__(self, application, project_id, changes=None):
        self.application = application
        self.project_id = project_id
        self.changes = changes or ProjectChangeService(application.projects)
        self.workbench = application.workbench(project_id)
        self.skills = SkillService(self.workbench.store)

    # -- identity guard ------------------------------------------------
    def _assert_request(self, request):
        """Reject any request that is not bound to this project service.

        This runs before any context, tool, store or model access so a request
        for project B can never be served with project A's workbench, records
        or models.
        """
        if request.project_id != self.project_id:
            raise ValueError(
                "Request project does not match this project intelligence service"
            )

    # -- per-task adapters --------------------------------------------
    def context(self, request):
        self._assert_request(request)
        return ProjectContextBuilder(self.application, request)

    def tools(self, request, context=None):
        self._assert_request(request)
        context = context or self.context(request)
        if context.application is not self.application or context.request != request:
            raise ValueError("Context does not match this project task and its read scope")
        return ProjectToolRegistry(
            self.application, request, context, self.skills, self.changes
        )

    # -- execution -----------------------------------------------------
    async def execute(self, request, task_id=None, cancel=None):
        self._assert_request(request)
        context = self.context(request)
        tools = self.tools(request, context=context)
        models = self.workbench.harness.models
        harness = HarnessService(
            self.workbench,
            models,
            context=context,
            tools=tools,
            skills=self.skills,
            record_metadata={
                "project_id": request.project_id,
                "project_revision_id": request.project_revision_id,
            },
        )
        return await harness.execute(request, task_id=task_id, cancel=cancel)

    def ask(self, request):
        self._assert_request(request)

        def run(task, cancel):
            result = asyncio.run(
                self.execute(request, task_id=task.id, cancel=cancel)
            )
            return {
                "receipt": result,
                "status": "failed" if result.get("status") in _FAILED else "completed",
            }

        return self.workbench.jobs.submit(
            "project.intelligence." + request.policy.role,
            run,
            receipt={
                "project_id": request.project_id,
                "project_revision_id": request.project_revision_id,
            },
        )

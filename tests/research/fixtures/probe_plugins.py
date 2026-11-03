import os
import time

from contract_driven_ai_flow.research.models import ProbeResult


class SafeProbe:
    protocol_version = 1

    def evaluate(self, context):
        print("Plugin output must not corrupt the wire channel")
        return ProbeResult(probe_id=context.probe_id, snapshot_id=context.snapshot_id, status="pass",
                           evidence={"pid": os.getpid(), "email": "person@example.org"}, message="password=hunter2")


class SlowProbe:
    protocol_version = 1

    def evaluate(self, context):
        if context.parameters.get("marker"):
            from pathlib import Path
            Path(context.parameters["marker"]).write_text("started")
        time.sleep(3)
        return ProbeResult(probe_id=context.probe_id, snapshot_id=context.snapshot_id, status="pass")


class MutationProbe:
    protocol_version = 1

    def evaluate(self, context):
        context.sample["values"][0][0] = 99
        return ProbeResult(probe_id=context.probe_id, snapshot_id=context.snapshot_id, status="pass")

"""Explicit user-program probes run in bounded owned workers."""

import json
import sys
import time
from pathlib import Path
from ..agent.privacy import sanitize_json, clean_text
from .models import ProbeOutput
from .process import run_process


def evaluate_program(workbench, invocation, run_id, plan, cancel):
    definition, instance = invocation.definition, invocation.instance
    base = dict(
        instance_id=instance.id,
        definition_id=definition.id,
        capability=definition.capability,
        execution="program",
        run_id=run_id,
        analysis_id=plan.analysis_id,
        snapshot_id=(
            invocation.targets[0].snapshot_id if len(invocation.targets) == 1 else None
        ),
        provenance="observed",
    )
    started = time.monotonic()
    try:
        snapshots = []
        for target in invocation.targets:
            if target.snapshot_id:
                snapshot = workbench.research.store.snapshot(target.snapshot_id)
                if (
                    definition.evidence in ("full", "full_coordinates")
                    and not snapshot.artifact_ref
                ):
                    raise ValueError(
                        "Required full data is unavailable; create a new capture run"
                    )
                snapshots.append(
                    snapshot.model_dump(
                        mode="json",
                        exclude=(
                            {"sample"} if definition.evidence == "metadata" else set()
                        ),
                    )
                )
        context = {
            "targets": [
                target.model_dump(mode="json") for target in invocation.targets
            ],
            "inputs": {
                role: target.model_dump(mode="json")
                for role, target in invocation.inputs.items()
            },
            "snapshots": snapshots,
            "semantics": invocation.semantics,
            "source_digest": plan.source_digest,
            "run_id": run_id,
        }
        request = {
            "root": str(workbench.root),
            "entrypoint": definition.entrypoint,
            "implementation_digest": definition.implementation_digest,
            "parameters": instance.parameters,
            "context": context,
        }
        code, stdout, stderr = run_process(
            [
                plan.config.interpreter or sys.executable,
                "-X",
                "utf8",
                str(Path(__file__).with_name("program_worker.py")),
            ],
            input=json.dumps(request, ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            ),
            cwd=workbench.root,
            cancel=cancel,
            timeout=instance.budget_ms / 1000,
        )
        # stdout is a protocol, so user programs must not print incidental logs.
        if code:
            raise ValueError(
                "Program worker exited with code "
                + str(code)
                + ": "
                + clean_text(stderr.decode("utf-8", errors="replace"), 1000)
            )
        value = json.loads(stdout)
        result = sanitize_json(value["result"])
        fidelity_order = {
            "exact": 0,
            "sampled": 1,
            "summary_only": 2,
            "metadata_only": 3,
            "unsupported": 4,
        }
        return ProbeOutput(
            **base,
            status=result["status"],
            message=clean_text(result.get("message", "")),
            fidelity=(
                "metadata_only"
                if definition.evidence == "metadata"
                else max(
                    (s["fidelity"] for s in snapshots),
                    key=lambda f: fidelity_order.get(f, 4),
                    default="metadata_only",
                )
            ),
            data={
                **result.get("data", {}),
                "program_digest": value["program_digest"],
                "coverage": [s["coverage"] for s in snapshots],
            },
            duration_ms=(time.monotonic() - started) * 1000,
        )
    except InterruptedError:
        raise
    except Exception as error:
        return ProbeOutput(
            **base,
            status="error",
            message=clean_text(
                str(error)
                if isinstance(error, (ValueError, TimeoutError))
                else "Program probe failed (" + type(error).__name__ + ")"
            ),
            duration_ms=(time.monotonic() - started) * 1000,
        )

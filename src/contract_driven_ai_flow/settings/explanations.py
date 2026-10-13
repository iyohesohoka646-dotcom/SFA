"""Explain saved evidence without sending live objects or adjacent source."""
from __future__ import annotations

import json
import re

from ..research.agent.privacy import sanitize_json
from ..research.models import Explanation


class ExplanationService:
    def __init__(self, research, settings):
        self.research, self.settings = research, settings

    def _operation(self, identifier):
        with self.research.store.connect() as db:
            row = db.execute("SELECT body FROM operations WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise LookupError("Scientific operation is unavailable")
        from ..research.models import OperationRecord
        return OperationRecord.model_validate_json(row[0])

    def context(self, operation_id, *, include_sample=False):
        operation = self._operation(operation_id)
        values = []
        for identifier in dict.fromkeys([*operation.input_snapshots, *operation.output_snapshots]):
            if len(values) >= 32:
                break
            snapshot = self.research.store.snapshot(identifier)
            value = {"id": identifier, "name": snapshot.name, "version": snapshot.version, "descriptor": snapshot.descriptor.model_dump(mode="json"),
                "statistics": snapshot.statistics, "fidelity": snapshot.fidelity, "redacted": snapshot.redacted, "truncation": snapshot.truncation}
            if include_sample:
                value["sample"] = snapshot.sample
            values.append(value)
        context = sanitize_json({"operation": {"id": operation.id, "label": operation.label, "provenance": operation.provenance,
            "source": operation.source.model_dump(mode="json") if operation.source else None, "duration_ms": operation.duration_ms}, "values": values})
        if len(json.dumps(context, ensure_ascii=False).encode()) > 256 * 1024:
            raise ValueError("Explanation context exceeds 256 KiB; select fewer or smaller values")
        return context

    async def explain(self, operation_id, *, provider_id, model, include_sample=False, operation_token=None):
        operation = self._operation(operation_id)
        context = self.context(operation_id, include_sample=include_sample)
        evidence = [operation.id, *operation.input_snapshots, *operation.output_snapshots]
        scope = {"samples": include_sample, "values": len(context["values"]), "bytes": len(json.dumps(context,ensure_ascii=False).encode()), "source": "selected expression only"}
        if self.settings.profile(provider_id).protocol == "offline":
            label = operation.label
            axis = re.search(r"mean\([^)]*axis\s*=\s*(\d+)", label)
            text = f"沿 axis={axis[1]} 求均值，聚合该维度。" if axis else "执行此源码表达式，输入输出及实际形状见运行证据。"
            if re.search(r"\([^)]*-[^)]*\)\s*/", label):
                text = "先减去中心值，再除以尺度，这是标准化形式；非有限值与尺度为零需要探针检查。"
            return Explanation(operation_id=operation.id,text=text,origin="rule",evidence=evidence,uncertainty=["实验语义与单位需要用户标注"],sent_scope={**scope,"requests":0})
        messages = [{"role":"system","content":"Explain this scientific computation in Simplified Chinese. Label observed mathematical facts separately from hypotheses about scientific meaning. Cite the supplied evidence IDs. Do not invent axis semantics or units. Never suggest that sampled values prove properties of the full data."},
                    {"role":"user","content":json.dumps(context,ensure_ascii=False,allow_nan=False)}]
        reply = await self.settings.complete(provider_id,messages,model=model,operation_id=operation_token)
        if reply.status != "connected":
            raise ValueError(reply.message)
        return Explanation(operation_id=operation.id,text=reply.text,origin="model",evidence=evidence,usage=reply.usage,sent_scope=scope,
            uncertainty=["模型文本尚未人工验证；实验意义属于推测，运行证据以记录为准"])

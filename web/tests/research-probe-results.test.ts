import { describe, expect, it } from "vitest";
import { latestProbeOutputs, sameParameters } from "../src/research/workspace/probe-results";
import type { SnapshotRef } from "../src/research/generated";
import type { ProbeInstance, ProbeOutput } from "../src/research/workspace/generated";
describe("exact multi-probe result display", () => {
  it("compares object parameters independent of JSON key insertion order", () => {
    expect(sameParameters({ precision: 3, options: { x: 1, y: 2 } }, { options: { y: 2, x: 1 }, precision: 3 })).toBe(true);
    expect(sameParameters({ x: [1, 2] }, { x: [2, 1] })).toBe(false);
  });
  it("keeps one latest result for each enabled probe and rejects previous runs or value versions", () => {
    const snapshot = { id: "s", run_id: "r" } as SnapshotRef;
    const instances = [{ id: "auto", enabled: true }, { id: "check", enabled: true }, { id: "disabled", enabled: false }] as ProbeInstance[];
    const result = (id: string, instance_id: string, snapshot_id = "s", run_id = "r"): ProbeOutput => ({ id, instance_id, snapshot_id, run_id,
      created_at: id === "new" ? "2026-10-04T03:00:00Z" : "2026-10-04T02:00:00Z", targets: [] } as unknown as ProbeOutput);
    const results = latestProbeOutputs([result("old", "check"), result("new", "check"), result("v", "auto", "old-value"), result("r", "auto", "s", "old-run"), result("off", "disabled"), result("ok", "auto")], snapshot, instances);
    expect([...results].map(([key, value]) => [key, value.id])).toEqual([["check", "new"], ["auto", "ok"]]);
  });
});

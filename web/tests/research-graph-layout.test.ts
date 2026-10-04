import { describe, expect, it } from "vitest";
import ELK from "elkjs/lib/elk.bundled.js";
import type { Edge, Node } from "@xyflow/react";
import { buildSemanticLayout, readSemanticLayout, semanticDimensions, semanticLayoutBounds, readableGraphViewport, type SemanticLayout } from "../src/graph-semantic-layout";
import browserDataFolded from "./fixtures/graph-browser-data-folded.json";
import compactLoop from "./fixtures/compact-loop-elk.json";

const handles = (input: number, output: number) => [
  ...Array.from({ length: input }, (_, i) => ({ id: "in" + i, direction: "input", name: "input " + i, kind: "data", boundary: false, original_ids: [] })),
  ...Array.from({ length: output }, (_, i) => ({ id: "out" + i, direction: "output", name: "output " + i, kind: "data", boundary: false, original_ids: [] })),
];
const node = (id: string, parentId?: string, plate = false, ports = handles(1, 1)): Node => ({ id, parentId, type: plate ? "plate" : "semantic", position: { x: 0, y: 0 }, style: semanticDimensions({ plate, label: id, handles: ports }), data: { label: id, handles: ports, collapsed: false } });

describe("measured semantic compound layout", () => {
  it("routes the actual nested loop projection vertically without experimental scanline compaction", async () => {
    const graph = structuredClone(compactLoop.graph) as ReturnType<typeof buildSemanticLayout>;
    const options = buildSemanticLayout([], [], 'DOWN').layoutOptions!;
    const update = (item: typeof graph) => {
      const constraints = item.layoutOptions?.['elk.portConstraints'];
      item.layoutOptions = { ...options, ...(constraints ? { 'elk.portConstraints': constraints } : {}) };
      item.children?.forEach(update);
    };
    update(graph);
    const layout = readSemanticLayout(await new ELK().layout(graph));
    expect(layout.nodes.size).toBe(12);
    expect(layout.edges.size).toBe(graph.edges!.length);
    for (const b of layout.nodes.values()) expect([b.x, b.y, b.width, b.height].every(Number.isFinite)).toBe(true);
    for (const route of layout.edges.values()) for (let i = 1; i < route.points.length; i++) {
      const a = route.points[i - 1], b = route.points[i];
      expect(a.x === b.x || a.y === b.y).toBe(true);
    }
  });
  it("uses compact aligned nodes and orthogonal channels with matching ports in both directions", async () => {
    for (const direction of ['RIGHT', 'DOWN']) {
      const nodes = ['a', 'b', 'c'].map(id => {
        const n = node(id);
        n.style = semanticDimensions({ label: id, plate: false, handles: handles(1, 1), compact: true });
        n.data.compact = true;
        return n;
      });
      const edges: Edge[] = ['b', 'c'].map(target => ({ id: 'a-' + target, source: 'a', target, sourceHandle: 'out0', targetHandle: 'in0' }));
      const input = buildSemanticLayout(nodes, edges, direction);
      const ports = input.children![0].ports!;
      expect(ports[0].layoutOptions!['elk.port.side']).toBe(direction === 'DOWN' ? 'NORTH' : 'WEST');
      expect(ports[1].layoutOptions!['elk.port.side']).toBe(direction === 'DOWN' ? 'SOUTH' : 'EAST');
      const layout = readSemanticLayout(await new ELK().layout(input));
      const b = layout.nodes.get('b')!, c = layout.nodes.get('c')!;
      expect(direction === 'DOWN' ? b.y : b.x).toBe(direction === 'DOWN' ? c.y : c.x);
      for (const e of edges) {
        const route = layout.edges.get(e.id)!, from = layout.nodes.get(e.source)!, to = layout.nodes.get(e.target)!;
        // ELK connects the outer faces of the 8 px handles, not their centers.
        expect(route.points[0]).toEqual({ x: from.x + from.ports.get('out0')!.x + (direction === 'RIGHT' ? 4 : 0), y: from.y + from.ports.get('out0')!.y + (direction === 'DOWN' ? 4 : 0) });
        expect(route.points.at(-1)).toEqual({ x: to.x + to.ports.get('in0')!.x - (direction === 'RIGHT' ? 4 : 0), y: to.y + to.ports.get('in0')!.y - (direction === 'DOWN' ? 4 : 0) });
        for (let i = 1; i < route.points.length; i++) {
          const p = route.points[i - 1], q = route.points[i];
          expect(p.x === q.x || p.y === q.y).toBe(true);
        }
      }
    }
  });
  it("measures input and output columns independently and reserves a real footer", () => {
    const both = semanticDimensions({ label: "normalize", plate: false, handles: handles(5, 4) });
    const inputOnly = semanticDimensions({ label: "normalize", plate: false, handles: handles(5, 0) });
    expect(both.height).toBe(inputOnly.height);
    expect(both.height).toBeGreaterThanOrEqual(160);
    expect(both.width).toBeGreaterThanOrEqual(228);
    const graph = buildSemanticLayout([node("n", undefined, false, handles(2, 2))], []);
    const ports = graph.children![0].ports!;
    expect(ports[0].y).toBe(ports[2].y);
    expect(ports[1].y).toBe(ports[3].y);
    expect(ports[0].layoutOptions!["elk.port.side"]).toBe("WEST");
    expect(ports[2].layoutOptions!["elk.port.side"]).toBe("EAST");
  });

  it("computes navigation bounds from fresh nested layout instead of stale mounted node positions", () => {
    const nodes = [node("file", undefined, true), node("loop", "file", true), node("leaf", "loop"), node("other")];
    nodes.forEach(n => { n.position = { x: 10000, y: -10000 }; n.style = { width: 1, height: 1 }; });
    const bounds = (x: number, y: number, width: number, height: number) => ({ x, y, width, height, ports: new Map() });
    const layout: SemanticLayout = { nodes: new Map([
      ["file", bounds(40, 80, 500, 400)], ["loop", bounds(120, 90, 220, 180)],
      ["leaf", bounds(70, 80, 228, 110)], ["other", bounds(800, 20, 300, 200)],
    ]), edges: new Map() };
    expect(semanticLayoutBounds(nodes, layout)).toEqual({ x: 40, y: 20, width: 1060, height: 460 });
    // Manual coordinates are applied to the ELK map before computing bounds.
    layout.nodes.get("leaf")!.x = 1000;
    expect(semanticLayoutBounds(nodes, layout)).toEqual({ x: 40, y: 20, width: 1348, height: 460 });
    expect(semanticLayoutBounds([], { nodes: new Map(), edges: new Map() })).toBeUndefined();
  });

  it("crops large initial graphs to their readable upper-left content and centers small scopes without enlarging text", () => {
    const pane = { width: 1333, height: 798 };
    for (const bounds of [
      { x: 30, y: 76, width: 4714.1, height: 2393.5 },
      { x: -820, y: 200, width: 10000, height: 160 },
      { x: 410, y: -100, width: 300, height: 20000 },
    ]) {
      const viewport = readableGraphViewport(bounds, pane)!;
      expect(viewport.zoom).toBe(0.75);
      expect(viewport.x + bounds.x * viewport.zoom).toBe(32);
      expect(viewport.y + bounds.y * viewport.zoom).toBe(48);
      expect(viewport.x + (bounds.x + bounds.width) * viewport.zoom > pane.width
        || viewport.y + (bounds.y + bounds.height) * viewport.zoom > pane.height).toBe(true);
    }
    const small = { x: 100, y: -200, width: 300, height: 160 };
    const viewport = readableGraphViewport(small, { width: 900, height: 600 })!;
    expect(viewport.zoom).toBe(1);
    expect(viewport.x + small.x).toBe(300);
    expect(viewport.y + small.y).toBe(228);
    const docked = readableGraphViewport({ x: 0, y: 0, width: 440, height: 200 }, { width: 450, height: 380 })!;
    expect(docked.zoom).toBeGreaterThanOrEqual(0.75); expect(docked.zoom).toBeLessThanOrEqual(1);
    expect(readableGraphViewport(small, { width: 0, height: 600 })).toBeUndefined();
  });

  it("lays out nested blocks with finite dimensions, no sibling overlaps, and complete routed edge endpoints", async () => {
    const nodes = [node("file", undefined, true, []), node("fn", "file", true, handles(0, 1)), node("a", "fn"), node("b", "fn"), node("c", "file")];
    const edges: Edge[] = [{ id: "inside", source: "a", target: "b", sourceHandle: "out0", targetHandle: "in0", label: "matrix" }, { id: "across", source: "b", target: "c", sourceHandle: "out0", targetHandle: "in0", label: "result" }];
    const output = await new ELK().layout(buildSemanticLayout(nodes, edges));
    const layout = readSemanticLayout(output);
    for (const n of nodes) {
      const p = layout.nodes.get(n.id)!;
      expect([p.x, p.y, p.width, p.height].every(Number.isFinite)).toBe(true);
      expect(p.width).toBeGreaterThan(0); expect(p.height).toBeGreaterThan(0);
      if (n.parentId) {
        const parent = layout.nodes.get(n.parentId)!;
        expect(p.x).toBeGreaterThanOrEqual(20); expect(p.y).toBeGreaterThanOrEqual(48);
        expect(p.x + p.width).toBeLessThanOrEqual(parent.width - 18);
        expect(p.y + p.height).toBeLessThanOrEqual(parent.height - 18);
      }
    }
    for (const a of nodes) for (const b of nodes) {
      if (a.id >= b.id || a.parentId !== b.parentId) continue;
      const x = layout.nodes.get(a.id)!, y = layout.nodes.get(b.id)!;
      expect(x.x + x.width <= y.x || y.x + y.width <= x.x || x.y + x.height <= y.y || y.y + y.height <= x.y).toBe(true);
    }
    for (const e of edges) {
      const route = layout.edges.get(e.id)!;
      expect(route.points.length).toBeGreaterThanOrEqual(2);
      expect(route.points.every(p => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
      const source = layout.nodes.get(e.source)!, target = layout.nodes.get(e.target)!;
      const absolute = (id: string) => { let x = 0, y = 0, current = nodes.find(n => n.id === id); while (current) { const p = layout.nodes.get(current.id)!; x += p.x; y += p.y; current = nodes.find(n => n.id === current!.parentId); } return { x, y }; };
      const s = absolute(e.source), t = absolute(e.target);
      expect(Math.abs(route.points[0].x - s.x - source.width)).toBeLessThanOrEqual(8);
      expect(Math.abs(route.points.at(-1)!.x - t.x)).toBeLessThanOrEqual(8);
    }
  });

  it("keeps a long dependency chain monotone without introducing folded return wires", async () => {
    const nodes = [node("file", undefined, true, []), ...Array.from({ length: 24 }, (_, i) => node("op" + i, "file"))];
    const edges: Edge[] = nodes.slice(2).map((n, i) => ({ id: "e" + i, source: "op" + i, target: n.id, sourceHandle: "out0", targetHandle: "in0", label: "control" }));
    const elk = new ELK(), input = buildSemanticLayout(nodes, edges);
    const result = readSemanticLayout(await elk.layout(input));
    for (const edge of edges) {
      const from = result.nodes.get(edge.source)!, to = result.nodes.get(edge.target)!;
      expect(to.x).toBeGreaterThan(from.x + from.width);
      const points = result.edges.get(edge.id)!.points;
      for (let i = 1; i < points.length; i++) expect(points[i].x).toBeGreaterThanOrEqual(points[i - 1].x);
    }
    expect(result.edges.size).toBe(edges.length);
    const repeat = readSemanticLayout(await elk.layout(buildSemanticLayout(nodes, edges)));
    expect([...repeat.nodes]).toEqual([...result.nodes]);
  });

  it("lays out the real browser data projection with collapsed conditions and every relation intact", async () => {
    // Anonymized IDs from the failing browser trace; topology, handles, labels,
    // and measured sizes are preserved. ELK's forced model-order comparison
    // previously read an unset modelOrder.maximum and rejected this graph.
    const nodes = browserDataFolded.nodes as Node[], edges = browserDataFolded.edges as Edge[];
    expect(nodes).toHaveLength(26); expect(edges).toHaveLength(51);
    const elk = new ELK(), output = readSemanticLayout(await elk.layout(buildSemanticLayout(nodes, edges)));
    expect(output.nodes.size).toBe(nodes.length); expect(output.edges.size).toBe(edges.length);
    for (const bounds of output.nodes.values()) expect([bounds.x, bounds.y, bounds.width, bounds.height].every(Number.isFinite)).toBe(true);
    for (const route of output.edges.values()) expect(route.points.every(p => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
    const root = output.nodes.get("file")!;
    expect(buildSemanticLayout(nodes, edges).layoutOptions!['elk.layered.wrapping.strategy']).toBe('OFF');
    expect(semanticLayoutBounds(nodes, output)).toEqual({ x: root.x, y: root.y, width: root.width, height: root.height });
    const viewport = readableGraphViewport(root, { width: 1333, height: 798 })!;
    expect(viewport.zoom).toBeGreaterThanOrEqual(0.75);
    const visibleContent = nodes.filter(n => n.type === "semantic").filter(n => {
      const b = output.nodes.get(n.id)!, x = viewport.x + (root.x + b.x) * viewport.zoom, y = viewport.y + (root.y + b.y) * viewport.zoom;
      return x < 1333 && y < 798 && x + b.width * viewport.zoom > 0 && y + b.height * viewport.zoom > 0;
    });
    expect(visibleContent.length).toBeGreaterThan(0);
    for (const a of nodes.slice(1)) for (const b of nodes.slice(1)) {
      if (a.id >= b.id) continue;
      const x = output.nodes.get(a.id)!, y = output.nodes.get(b.id)!;
      expect(x.x + x.width <= y.x || y.x + y.width <= x.x || x.y + x.height <= y.y || y.y + y.height <= x.y).toBe(true);
    }
    const repeat = readSemanticLayout(await elk.layout(buildSemanticLayout(nodes, edges)));
    expect([...repeat.nodes]).toEqual([...output.nodes]);
  });
});

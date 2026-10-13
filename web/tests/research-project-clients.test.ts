import { afterEach, describe, expect, it, vi } from "vitest";
import { createResearchClient } from "../src/research/client";
import { createWorkbenchClient } from "../src/research/workspace/WorkbenchClient";
vi.mock("../src/api", () => ({
  headers: () => ({}),
  ApiError: class extends Error {
    constructor(
      message: string,
      public status = 0,
    ) {
      super(message);
    }
  },
}));

afterEach(() => vi.unstubAllGlobals());
describe("immutable research transports", () => {
  it("keeps concurrent project requests and artifact reads on their original owner", async () => {
    const urls: string[] = [];
    let release!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        urls.push(url);
        return url.includes("/A/") && url.endsWith("/configuration")
          ? new Promise<Response>((resolve) => {
              release = resolve;
            })
          : Promise.resolve(
              new Response(url.includes("/artifacts/") ? "plot" : "{}"),
            );
      }),
    );
    const a = createResearchClient("/api/v1/research/projects/A");
    const b = createResearchClient("/api/v1/research/projects/B");
    const wa = createWorkbenchClient(a.request, a.apiPrefix),
      wb = createWorkbenchClient(b.request, b.apiPrefix);
    const first = wa.configuration();
    await wb.configuration();
    await wb.artifact("plot");
    release(new Response("{}"));
    await first;
    await wa.artifact("plot");
    expect(urls).toEqual([
      "/api/v1/research/projects/A/workbench/configuration",
      "/api/v1/research/projects/B/workbench/configuration",
      "/api/v1/research/projects/B/workbench/artifacts/plot",
      "/api/v1/research/projects/A/workbench/artifacts/plot",
    ]);
  });
  it("forwards abort signals and preserves structured HTTP failures", async () => {
    const abort = new AbortController();
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Wrong revision" }), {
          status: 409,
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createResearchClient("/api/v1/research/projects/A");
    await expect(
      client.client.snapshot("id /", abort.signal),
    ).rejects.toMatchObject({ status: 409, message: "Wrong revision" });
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/v1/research/projects/A/snapshots/id%20%2F",
      expect.objectContaining({ signal: abort.signal }),
    ]);
  });
});

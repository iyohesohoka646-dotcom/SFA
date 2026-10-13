/** Unit tests for the standalone project chooser/entry-editor client boundary. */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  commandError,
  createProjectCommands,
  legacyrequest,
  ProjectIdentityConflict,
  type ProjectTransport,
  type ProjectTransportOptions,
} from "../src/research/projects/projectCommands";
import {
  draftFromEntry,
  entryFromDraft,
  newEntryDraft,
  normalizeTarget,
  parseArgumentLines,
  parseEnvironmentLines,
  ProjectRunConfigurations,
} from "../src/research/projects/ProjectRunConfigurations";
import { ProjectHost } from "../src/research/projects/ProjectHost";
import type { ResearchProject, RunConfiguration } from "../src/research/projects/generated";

interface Call {
  path: string;
  options: ProjectTransportOptions;
}

function recorder(handler: (call: Call) => unknown) {
  const calls: Call[] = [];
  const transport: ProjectTransport = <T,>(
    path: string,
    options: ProjectTransportOptions = {},
  ) => {
    const call = { path, options };
    calls.push(call);
    return Promise.resolve(handler(call) as T);
  };
  return { calls, transport };
}

const projectRecord = (id: string, revision: string | null = "rev1"): ResearchProject =>
  ({
    protocol_version: 1,
    id,
    root: "/root/" + id,
    name: id,
    latest_revision_id: revision,
    source_roots: ["."],
    include: ["**/*.py"],
    exclude: [],
    run_configurations: [],
  }) as ResearchProject;

describe("createProjectCommands", () => {
  it("closes over the injected transport and never talks while constructing", () => {
    const { calls, transport } = recorder(() => projectRecord("p1"));
    const commands = createProjectCommands(transport);
    const client = commands.forProject("p1");
    expect(calls.length).toBe(0);
    expect(Object.isFrozen(commands)).toBe(true);
    expect(Object.isFrozen(client)).toBe(true);
    expect(client.projectId).toBe("p1");
    // The default transport is the shared research request helper, untouched.
    expect(typeof legacyrequest).toBe("function");
  });

  it("isolates every project id inside its own encoded path", async () => {
    const { calls, transport } = recorder((call) =>
      call.path === "/projects"
        ? [projectRecord("a/b"), projectRecord("c")]
        : projectRecord(decodeURIComponent(call.path.split("/")[2])),
    );
    const commands = createProjectCommands(transport);
    const list = await commands.recent();
    expect(list.map((item) => item.id)).toEqual(["a/b", "c"]);
    const a = await commands.forProject("a/b").info();
    const c = await commands.forProject("c").info();
    expect(a.id).toBe("a/b");
    expect(c.id).toBe("c");
    expect(calls.map((call) => call.path)).toEqual([
      "/projects",
      "/projects/a%2Fb",
      "/projects/c",
    ]);
    expect(commands.forProject("a/b")).not.toBe(commands.forProject("a/b"));
  });

  it("never delivers an index or execute command from factory construction", () => {
    const { calls, transport } = recorder(() => projectRecord("p1"));
    const commands = createProjectCommands(transport);
    commands.forProject("p1").runtime;
    commands.forProject("p1").execute;
    expect(calls.length).toBe(0);
  });

  it("opens a folder explicitly and indexes only when asked", async () => {
    const { calls, transport } = recorder((call) =>
      call.path === "/projects/open" ? projectRecord("p1", null) : projectRecord("p1", null),
    );
    const commands = createProjectCommands(transport);
    const opened = await commands.open("  /root/p1  ");
    expect(opened.id).toBe("p1");
    expect(calls[0].path).toBe("/projects/open");
    expect(calls[0].options.method).toBe("POST");
    expect(calls[0].options.body).toEqual({ path: "/root/p1" });
    const task = await commands.forProject("p1").index(null);
    expect(task).toBeTruthy();
    expect(calls[1].path).toBe("/projects/p1/index");
    expect(calls[1].options.body).toEqual({ expected_revision: null });
  });

  it("forwards the abort signal on every request", async () => {
    const { calls, transport } = recorder(() => projectRecord("p1"));
    const commands = createProjectCommands(transport);
    const controller = new AbortController();
    await commands.recent(controller.signal);
    await commands.forProject("p1").info(controller.signal);
    await commands.forProject("p1").task("t1", controller.signal);
    await commands.forProject("p1").cancelTask("t1", controller.signal);
    await commands.runtime(controller.signal);
    expect(calls.length).toBe(5);
    for (const call of calls) expect(call.options.signal).toBe(controller.signal);
  });

  it("keeps the machine runtime outside the project prefix", async () => {
    const state = { revision: 3, interpreters: [{ id: "py311" }], environments: [], legacy_environment: [] };
    const { calls, transport } = recorder((call) =>
      call.path === "/runtime" ||
      call.path.startsWith("/runtime/")
        ? state
        : projectRecord("p1"),
    );
    const commands = createProjectCommands(transport);
    const current = await commands.forProject("p1").runtime();
    expect(current.revision).toBe(3);
    await commands.forProject("p1").registerInterpreter("py311", "C:/py/python.exe", 3);
    await commands.forProject("p1").registerEnvironment("lab", { TOKEN: "s" }, 4);
    expect(calls.map((call) => call.path)).toEqual([
      "/runtime",
      "/runtime/interpreters/py311",
      "/runtime/environments/lab",
    ]);
    expect(calls[1].options.method).toBe("PUT");
    expect(calls[1].options.body).toEqual({ path: "C:/py/python.exe", expected_revision: 3 });
    expect(calls[2].options.body).toEqual({ values: { TOKEN: "s" }, expected_revision: 4 });
    for (const call of calls) expect(call.path.startsWith("/projects")).toBe(false);
  });

  it("sends entries with the expected config revision and surfaces 409", async () => {
    const entry: RunConfiguration = {
      id: "e1",
      name: "main",
      kind: "script",
      target: "main.py",
      cwd: ".",
      interpreter_ref: "",
      arguments: [],
      environment: [],
      options: {},
    };
    const { calls, transport } = recorder((call) => {
      if (call.options.method === "PUT")
        return { revision: 4, run_configurations: [entry] };
      return {
        project_id: "p1",
        revision_id: "rev1",
        config_revision: 3,
        entries: [entry],
        candidates: [],
      };
    });
    const commands = createProjectCommands(transport);
    const page = await commands.forProject("p1").entries("rev1");
    expect(page.config_revision).toBe(3);
    const saved = await commands.forProject("p1").saveEntries([entry], page.config_revision);
    expect(saved.revision).toBe(4);
    expect(calls[1].path).toBe("/projects/p1/entries");
    expect(calls[1].options.method).toBe("PUT");
    expect(calls[1].options.body).toEqual({ expected_revision: 3, entries: [entry] });

    const conflict = Object.assign(new Error("Configuration revision conflict"), { status: 409 });
    const failing = createProjectCommands(() => Promise.reject(conflict));
    await expect(failing.forProject("p1").saveEntries([entry], 3)).rejects.toThrow(
      "Configuration revision conflict",
    );
    expect(commandError(conflict).status).toBe(409);
  });

  it("refuses plan and identity drift instead of inventing a revision", async () => {
    const { calls, transport } = recorder(() => projectRecord("other", "rev9"));
    const commands = createProjectCommands(transport);
    await expect(
      commands.forProject("p1").plan({ configuration_id: "e1", revision_id: "" }),
    ).rejects.toThrow(/revision/i);
    expect(calls.length).toBe(0);
    await expect(commands.forProject("p1").info()).rejects.toBeInstanceOf(ProjectIdentityConflict);
  });

  it("rejects identity drift on entries and plans", async () => {
    const { transport } = recorder(() => ({
      project_id: "p1",
      revision_id: "rev9",
      config_revision: 0,
      entries: [],
      candidates: [],
    }));
    const commands = createProjectCommands(transport);
    await expect(commands.forProject("p1").entries("rev1")).rejects.toBeInstanceOf(
      ProjectIdentityConflict,
    );
  });
});

describe("entry definitions", () => {
  it("keeps script targets and normalises module bodies", () => {
    expect(normalizeTarget("script", "pkg/main.py")).toBe("pkg/main.py");
    expect(normalizeTarget("module", "pkg/main.py")).toBe("pkg.main");
    expect(normalizeTarget("module", "pkg\\sub\\app")).toBe("pkg.sub.app");
    expect(normalizeTarget("module", "pkg.sub")).toBe("pkg.sub");
  });

  it("maps drafts to entries with one argument per line", () => {
    const draft = { ...newEntryDraft(), name: " run ", target: "pkg/main.py", kind: "module" as const };
    draft.argumentsText = "--flag\n\n  two words  \r\n--last";
    const entry = entryFromDraft(draft);
    expect(entry.kind).toBe("module");
    expect(entry.target).toBe("pkg.main");
    expect(entry.name).toBe("run");
    expect(entry.arguments).toEqual(["--flag", "two words", "--last"]);
    expect(entry.cwd).toBe(".");
    expect(entry.interpreter_ref).toBe("");
    expect(entry.environment).toEqual([]);
    // Machine default interpreter stores no path in the project definition.
    expect(entryFromDraft({ ...draft, interpreterRef: "py311" }).interpreter_ref).toBe("py311");
    expect(entryFromDraft({ ...draft, environmentRef: "lab" }).environment).toEqual(["lab"]);
  });

  it("round-trips an existing entry into a draft and back", () => {
    const entry: RunConfiguration = {
      id: "e1",
      name: "main",
      kind: "script",
      target: "main.py",
      cwd: "work",
      interpreter_ref: "py311",
      arguments: ["a", "b"],
      environment: ["lab"],
      options: { keep: true },
    };
    const draft = draftFromEntry(entry, 0);
    expect(draft.argumentsText).toBe("a\nb");
    expect(draft.index).toBe(0);
    const again = entryFromDraft(draft);
    expect(again.target).toBe("main.py");
    expect(again.arguments).toEqual(["a", "b"]);
    expect(parseArgumentLines("one\n  \ntwo")).toEqual(["one", "two"]);
  });

  it("parses host-private environment lines and reports bad names", () => {
    const ok = parseEnvironmentLines("TOKEN=secret\nEMPTY=\n");
    expect(ok.values).toEqual({ TOKEN: "secret", EMPTY: "" });
    expect(ok.invalid).toEqual([]);
    const bad = parseEnvironmentLines("1BAD=value\nno-equals");
    expect(bad.invalid).toEqual(["1BAD=value", "no-equals"]);
    expect(Object.keys(bad.values)).toEqual([]);
  });
});

describe("component smoke", () => {
  it("renders the compact chooser without contacting the transport", () => {
    const { calls, transport } = recorder(() => projectRecord("p1"));
    const commands = createProjectCommands(transport);
    const markup = renderToStaticMarkup(
      createElement(ProjectHost, { client: commands }, () =>
        createElement("span", null, "child"),
      ),
    );
    expect(markup).toContain("Choose project");
    expect(markup).toContain("No project open");
    expect(calls.length).toBe(0);
  });

  it("renders the entry editor labels", () => {
    const { calls, transport } = recorder(() => projectRecord("p1"));
    const commands = createProjectCommands(transport);
    const markup = renderToStaticMarkup(
      createElement(ProjectRunConfigurations, {
        projectId: "p1",
        revisionId: "rev1",
        onSelect: () => {},
        onError: () => {},
        client: commands,
      }),
    );
    expect(markup).toContain("Run entries");
    expect(markup).toContain("Advanced: machine references");
    expect(calls.length).toBe(0);
  });
});

import { useResearchServices } from "./ResearchServices";
import { useEffect, useState } from "react";

import { ToolLibrary } from "./ToolLibrary";
import type { ProbeDefinition, ProbeResource, TaskRecord, WorkbenchConfig } from "./generated";
import { ParameterForm } from "./ParameterForm";
import { ProbeTemplateLibrary } from "./ProbeTemplateLibrary";
import { initialProbeParameters } from "./probe-configuration";
import "./probe-management.css";
import {
  purposeNames,
  targetNames,
  implementationNames,
} from "./probe-taxonomy";
export function ProbeLibrary({
  definitions,
  interpreter,
  tasks,
  onTask,
  onError,
  onRefresh,
  onBind,
  config,
  onChange,
  onSave,
  onModelSettings,
}: {
  definitions: ProbeDefinition[];
  interpreter: string;
  tasks: TaskRecord[];
  onTask: (t: TaskRecord) => void;
  onError: (s: string) => void;
  onRefresh: () => void;
  onBind: (id: string) => void;
  config?: WorkbenchConfig;
  onChange?: (config: WorkbenchConfig) => void;
  onSave?: () => Promise<unknown>;
  onModelSettings?: () => void;
}) {
  const { workbench: wb } = useResearchServices();
  const [tab, setTab] = useState("definitions"),
    [target, setTarget] = useState("data"),
    [purpose, setPurpose] = useState("all"),
    [implementation, setImplementation] = useState("all"),
    [query, setQuery] = useState(""),
    [resources, setResources] = useState<ProbeResource[]>([]),
    [draft, setDraft] = useState(""),
    [skill, setSkill] = useState(""),
    [skills, setSkills] = useState<{ id: string; title: string }[]>([]),
    [editingDefaults, setEditingDefaults] = useState<string>(),
    [savingDefaults, setSavingDefaults] = useState(false),
    [notice, setNotice] = useState("");
  const visibleDefinitions = definitions.filter((definition) =>
    definition.id !== "view.auto" && (target === "all" || definition.supported_targets.includes(target as never))
    && (purpose === "all" || definition.capability === purpose)
    && (implementation === "all" || definition.execution === implementation)
    && (definition.label + " " + definition.id).toLowerCase().includes(query.trim().toLowerCase()),
  );
  const refresh = () =>
    void Promise.all([wb.resources(), wb.skills()])
      .then(([r, s]) => {
        setResources(r);
        setSkills(s);
        onRefresh();
      })
      .catch((e) => onError(e.message));
  useEffect(refresh, []);
  return (
    <div className="probe-library">
      <div className="wb-view-toolbar">
        <strong>探针库</strong>
        <button onClick={refresh}>刷新</button>
      </div>
      <div className="wb-local-tabs">
        {[
          ["definitions", "能力目录"],
          ["templates", "探针模板"],
          ["public", "可获取资源"],
          ["installed", "已安装 / 自定义"],
          ["skills", "Skill"],
        ].map(([id, label]) => (
          <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "templates" && config && onChange && onSave ? <ProbeTemplateLibrary config={config} definitions={definitions} onChange={onChange} onSave={onSave} onError={onError} onModelSettings={onModelSettings} /> : tab === "public" ? (
        <ToolLibrary
          interpreter={interpreter}
          tasks={tasks}
          onTask={onTask}
          onError={onError}
        />
      ) : tab === "definitions" ? (
        <>
          <div className="library-filters">
            <select
              aria-label="探针作用对象"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="all">全部对象</option>
              {Object.entries(targetNames)
                .filter(([k]) => !["folder", "stream"].includes(k))
                .map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
            </select>
            <select
              aria-label="探针用途"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
            >
              <option value="all">全部用途</option>
              {Object.entries(purposeNames).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
            <select
              aria-label="探针实现方式"
              value={implementation}
              onChange={(e) => setImplementation(e.target.value)}
            >
              <option value="all">全部实现</option>
              {Object.entries(implementationNames).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
            <input
              type="search"
              aria-label="搜索探针库"
              value={query}
              placeholder="搜索探针"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="library-definition-list">
            {Object.entries(purposeNames)
              .filter(([k]) => visibleDefinitions.some((definition) => definition.capability === k))
              .map(([k, label]) => (
                <section key={k}>
                  <h3>{label}</h3>
                  {visibleDefinitions
                    .filter((d) => d.capability === k)
                    .map((d) => (
                      <div className="library-definition" key={d.id}>
                        <span>
                          <strong>{d.label}</strong>
                          <small>
                            {implementationNames[d.execution]} ·{" "}
                            {d.input_mode === "joint" ? "联合输入" : "逐个执行"}{" "}
                            · v{d.version}
                            {config?.probe_defaults?.[d.id] ? " · 自定义默认参数" : ""}
                          </small>
                        </span>
                        <div className="library-definition-actions">
                          <button aria-label={"配置 " + d.label + " 默认参数"} aria-expanded={editingDefaults === d.id}
                            onClick={() => { setEditingDefaults(editingDefaults === d.id ? undefined : d.id); setNotice(""); }}>默认参数</button>
                          <button onClick={() => onBind(d.id)}>绑定</button>
                        </div>
                        {editingDefaults === d.id && <div className="library-default-editor">
                          <ParameterForm schema={d.parameter_schema} value={initialProbeParameters(d, config?.probe_defaults?.[d.id])}
                            onChange={(parameters) => {
                              if (config && onChange) {
                                onChange({ ...config, probe_defaults: { ...config.probe_defaults, [d.id]: parameters } });
                                setNotice("");
                              }
                            }} modelPolicy={config?.harness.find((policy) => policy.role === "probe")} onModelSettings={onModelSettings} />
                          <div className="library-default-actions">
                            <small>用于新绑定，已有绑定保留各自参数。</small>
                            <button disabled={!config || !onChange || savingDefaults} onClick={() => {
                              if (!config || !onChange) return;
                              const next = { ...config.probe_defaults };
                              delete next[d.id];
                              onChange({ ...config, probe_defaults: next });
                              setNotice("已恢复内置参数，请保存。");
                            }}>恢复内置参数</button>
                            <button className="wb-primary" disabled={!onSave || savingDefaults}
                              onClick={() => {
                                if (!onSave) return;
                                setSavingDefaults(true);
                                void onSave().then(() => setNotice("默认参数已保存。"))
                                  .catch((error) => onError(error.message)).finally(() => setSavingDefaults(false));
                              }}>{savingDefaults ? "保存中…" : "保存默认参数"}</button>
                          </div>
                          {notice && <span role="status">{notice}</span>}
                        </div>}
                      </div>
                    ))}
                </section>
              ))}
            {!visibleDefinitions.length && <p className="probe-empty">此条件下没有探针，请调整筛选。</p>}
          </div>
        </>
      ) : tab === "skills" ? (
        <div className="wb-form">
          <label>
            Skill 文件路径
            <input
              aria-label="Skill 文件路径"
              value={skill}
              onChange={(e) => setSkill(e.target.value)}
            />
          </label>
          <button
            disabled={!skill}
            onClick={() =>
              void wb
                .registerSkill(skill)
                .then(refresh)
                .catch((e) => onError(e.message))
            }
          >
            导入 Skill
          </button>
          {skills.map((s) => (
            <div key={s.id}>
              <strong>{s.title}</strong>
              <small>{s.id}</small>
            </div>
          ))}
        </div>
      ) : (
        <div className="resource-manager">
          {resources
            .filter((r) => r.source !== "public")
            .map((r) => (
              <div className="resource-row" key={r.id}>
                <strong>{r.label}</strong>
                <span>
                  v{r.version} · {r.status}
                  {r.pending_version ? " · 草案 v" + r.pending_version : ""}
                </span>
                {r.pending_version && (
                  <button
                    onClick={() =>
                      void wb
                        .resourceDraft(r.id)
                        .then((d) => setDraft(JSON.stringify(d, null, 2)))
                        .catch((e) => onError(e.message))
                    }
                  >
                    查看草案
                  </button>
                )}
                {r.pending_version && (
                  <button
                    onClick={() =>
                      void wb
                        .resourceAction(r.id, "enable", r.review_digest)
                        .then(refresh)
                        .catch((e) => onError(e.message))
                    }
                  >
                    启用草案
                  </button>
                )}
                <button
                  disabled={r.source === "builtin"}
                  onClick={() =>
                    void wb
                      .resourceAction(
                        r.id,
                        r.status === "installed" ? "disable" : "enable",
                        r.review_digest,
                      )
                      .then(refresh)
                      .catch((e) => onError(e.message))
                  }
                >
                  {r.status === "installed" ? "停用" : "校验并启用"}
                </button>
                {r.diagnostics.length > 0 && (
                  <span role="status">{r.diagnostics.join("；")}</span>
                )}
              </div>
            ))}
          <div className="wb-form">
            <label>
              导入扩展清单
              <input
                type="file"
                aria-label="导入扩展清单"
                accept=".json"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void f.text().then(setDraft);
                }}
              />
            </label>
            <details>
              <summary>自定义定义</summary>
              <textarea
                aria-label="扩展清单 JSON"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder='{"id":"my-probes","label":"我的探针","version":"1","definitions":[]}'
              />
            </details>
            <button
              disabled={!draft}
              onClick={() => {
                try {
                  void wb
                    .importResource(JSON.parse(draft))
                    .then(refresh)
                    .catch((e) => onError(e.message));
                } catch {
                  onError("扩展清单不是有效 JSON");
                }
              }}
            >
              导入为待审查资源
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

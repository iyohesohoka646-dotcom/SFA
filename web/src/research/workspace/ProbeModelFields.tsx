import { useEffect, useState } from "react";
import { models, type PublicProviderProfile } from "../../settings/client";
import { availableModels } from "./probe-configuration";
import "./probe-management.css";

export function ProbeModelFields({ value, onChange, modelPolicy, onModelSettings, labelPrefix = "探针" }: {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  modelPolicy?: { provider_id?: string; model?: string | null };
  onModelSettings?: () => void;
  labelPrefix?: string;
}) {
  const [profiles, setProfiles] = useState<PublicProviderProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void models.list(controller.signal).then((list) => {
      setProfiles(list);
      setError("");
    }).catch((reason) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "模型服务读取失败");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    const update = () => setRefresh((current) => current + 1);
    window.addEventListener("cdaf-models-changed", update);
    return () => window.removeEventListener("cdaf-models-changed", update);
  }, []);
  const provider = String(value.provider_id ?? "");
  const inheritedProvider = modelPolicy?.provider_id || "offline";
  const effectiveProvider = provider || inheritedProvider;
  const profile = profiles.find((item) => item.id === effectiveProvider);
  const model = String(value.model ?? "");
  const choices = availableModels(profile);
  const inheritedModel = !provider && modelPolicy?.model || profile?.default_model || "";
  return (
    <div className="probe-model-fields">
      <label>
        模型服务
        <select aria-label={labelPrefix + "模型服务"} value={provider} disabled={loading && !profiles.length}
          onChange={(event) => {
            const id = event.target.value;
            onChange({ ...value, provider_id: id, model: id ? profiles.find((item) => item.id === id)?.default_model || "" : "" });
          }}>
          <option value="">{loading && !profiles.length ? "读取模型服务…" : "默认服务 · " + inheritedProvider}</option>
          {provider && !profiles.some((item) => item.id === provider) && <option value={provider}>{provider} · 未配置</option>}
          {profiles.map((item) => <option key={item.id} value={item.id}>{item.id}{item.protocol === "offline" ? " · 离线规则" : ""}</option>)}
        </select>
      </label>
      <label>
        模型
        <select aria-label={labelPrefix + "模型"} value={model} disabled={loading && !profiles.length}
          onChange={(event) => onChange({ ...value, model: event.target.value })}>
          <option value="">{inheritedModel ? "默认模型 · " + inheritedModel : "服务默认模型"}</option>
          {model && !choices.includes(model) && <option value={model}>{model} · 已保存值</option>}
          {choices.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
      </label>
      <div className="probe-model-actions">
        {onModelSettings && <button type="button" aria-label={labelPrefix + "模型设置"} onClick={onModelSettings}>模型设置</button>}
        <button type="button" onClick={() => setRefresh((current) => current + 1)} disabled={loading} aria-label={labelPrefix + "刷新模型服务"}>刷新服务</button>
      </div>
      {error && <span className="probe-form-error" role="alert">{error}</span>}
      {!loading && !error && profile && !choices.length && <span className="probe-field-hint">此服务尚未保存模型，请在模型设置中添加。</span>}
    </div>
  );
}

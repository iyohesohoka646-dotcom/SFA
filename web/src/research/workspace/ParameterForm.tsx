import { useState } from "react";
import { ProbeModelFields } from "./ProbeModelFields";
import { type ParameterField } from "./probe-configuration";
import "./probe-management.css";

const labels: Record<string, string> = {
  precision: "小数位数", show_values: "显示数值", show_coordinates: "显示坐标",
  row_labels: "行名称", column_labels: "列名称", palette: "配色", scale: "色阶", unit: "单位",
  kind: "图形", operation: "运算", broadcast: "允许广播", missing: "缺失值策略",
  alignment: "坐标对齐", allow_cross_run: "允许跨运行", flatten: "展开多维数据",
  method: "方法", axis: "聚合轴", keys: "连接键", how: "连接方式", cardinality: "连接基数",
  shared_scale: "共同色阶", linked_zoom: "联动缩放", prompt: "补充指令", task: "任务",
  focus: "关注重点", constraints: "约束", output_format: "输出格式",
  provider_id: "模型服务", model: "模型", skill_id: "Skill", expected: "期望值",
  min: "最小值", max: "最大值", max_ratio: "最大缺失比例", tolerance: "容差",
  max_ms: "耗时上限 ms", maximum_ms: "耗时上限 ms", max_bytes: "大小上限 bytes",
  enable_expensive: "允许完整数据计算", other_shape: "另一对象形状",
};
const choiceLabels: Record<string, string> = {
  diverging: "发散", sequential: "连续", gray: "灰度", linear: "线性", log: "对数",
  symmetric: "对称", heatmap: "热图", line: "折线", histogram: "直方图",
  error: "遇到缺失值停止", propagate: "保留缺失值", pairwise: "使用成对有效值",
  coordinates: "按坐标", positional: "按位置", subtract: "相减", add: "相加", multiply: "相乘",
  divide: "相除", broadcast: "广播", matmul: "矩阵乘法", mean: "均值", sum: "求和",
  min: "最小值", max: "最大值", std: "标准差", median: "中位数", inner: "交集", left: "保留左表",
  right: "保留右表", outer: "并集", one_to_one: "一对一", one_to_many: "一对多",
  many_to_one: "多对一", many_to_many: "多对多",
};
const textFields = new Set(["task", "focus", "constraints", "output_format", "prompt"]);
const hasType = (field: ParameterField, type: string) => field.type === type || Array.isArray(field.type) && field.type.includes(type);

export function ParameterForm({ schema, value, onChange, modelPolicy, onModelSettings }: {
  schema: Record<string, unknown>;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  modelPolicy?: { provider_id?: string; model?: string | null };
  onModelSettings?: () => void;
}) {
  const [advanced, setAdvanced] = useState(false), [raw, setRaw] = useState(""), [error, setError] = useState("");
  const properties = (schema.properties ?? {}) as Record<string, ParameterField>;
  const modelFields = "provider_id" in properties && "model" in properties;
  const update = (key: string, next: unknown) => onChange({ ...value, [key]: next });
  const unset = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };
  const fieldValue = (key: string, field: ParameterField) => key in value ? value[key] : field.default;
  return (
    <div className="parameter-form wb-form compact">
      {modelFields && <ProbeModelFields value={value} onChange={onChange} modelPolicy={modelPolicy} onModelSettings={onModelSettings} />}
      {Object.entries(properties).filter(([key]) => key !== "semantics" && !(modelFields && ["provider_id", "model"].includes(key))).map(([key, field]) => {
        const label = field.title || labels[key] || key;
        const current = fieldValue(key, field);
        const stringEnum = field.enum?.every((item) => typeof item === "string");
        const optionValue = (item: unknown, index: number) => stringEnum ? String(item) : String(index);
        let defaultValue = "-1";
        while (field.enum?.some((item, index) => optionValue(item, index) === defaultValue)) defaultValue = "_" + defaultValue;
        const selectedIndex = field.enum?.findIndex((item) => item === current) ?? -1;
        if (!field.enum && !["boolean", "integer", "number", "array", "string"].some((type) => hasType(field, type))) return null;
        return (
          <label key={key} className={textFields.has(key) ? "probe-requirement-field" : undefined}>
            {label}
            {hasType(field, "boolean") ? (
              <input aria-label={label} type="checkbox" checked={Boolean(current)} onChange={(event) => update(key, event.target.checked)} />
            ) : field.enum ? (
              <select aria-label={label} value={selectedIndex < 0 ? defaultValue : optionValue(field.enum[selectedIndex], selectedIndex)}
                onChange={(event) => event.target.value === defaultValue ? unset(key)
                  : update(key, stringEnum ? event.target.value : field.enum![Number(event.target.value)])}>
                <option value={defaultValue}>默认{field.default !== undefined ? " · " + (choiceLabels[String(field.default)] || String(field.default)) : ""}</option>
                {field.enum.map((item, index) => <option key={index} value={optionValue(item, index)}>{choiceLabels[String(item)] || String(item)}</option>)}
              </select>
            ) : hasType(field, "integer") || hasType(field, "number") ? (
              <input aria-label={label} type="number" min={field.minimum} max={field.maximum} step={hasType(field, "integer") ? 1 : "any"}
                value={current === null || current === undefined ? "" : String(current)}
                placeholder={hasType(field, "null") ? "不限制" : undefined}
                onChange={(event) => event.target.value === "" ? hasType(field, "null") ? update(key, null) : unset(key) : update(key, Number(event.target.value))} />
            ) : hasType(field, "array") ? (
              <input aria-label={label}
                value={Array.isArray(current) ? current.map((item) => item === null ? "*" : String(item)).join(", ") : ""}
                placeholder={field.description || "逗号分隔"}
                onChange={(event) => update(key, event.target.value.trim() ? event.target.value.split(",").map((part) => {
                  const item = part.trim();
                  if (hasType(field.items ?? {}, "null") && ["*", "null"].includes(item)) return null;
                  if (hasType(field.items ?? {}, "integer") || hasType(field.items ?? {}, "number"))
                    return item && Number.isFinite(Number(item)) ? Number(item) : item;
                  return item;
                }) : [])} />
            ) : textFields.has(key) ? (
              <textarea aria-label={label} rows={key === "task" ? 3 : 2} value={String(current ?? "")} onChange={(event) => update(key, event.target.value)} />
            ) : (
              <input aria-label={label} value={String(current ?? "")} onChange={(event) => update(key, event.target.value)} />
            )}
          </label>
        );
      })}
      <details className="probe-advanced" open={advanced} onToggle={(event) => {
        const open = event.currentTarget.open;
        setAdvanced(open);
        if (open) { setRaw(JSON.stringify(value, null, 2)); setError(""); }
      }}>
        <summary>高级参数</summary>
        {advanced && <>
          <textarea aria-label="探针参数 JSON" value={raw} onChange={(event) => setRaw(event.target.value)} />
          <button type="button" onClick={() => {
            try {
              const parsed = JSON.parse(raw);
              if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw Error();
              onChange(parsed);
              setError("");
              setAdvanced(false);
            } catch { setError("参数须为 JSON 对象"); }
          }}>应用参数</button>
          {error && <span className="probe-form-error" role="alert">{error}</span>}
        </>}
      </details>
    </div>
  );
}

# SFA 示例：数据处理流水线

一个完整的、可一键运行的 SFA 演示项目。展示从拓扑定义到运行观测的完整闭环，
包含 5 个原子模块、4 条管道、1 个断言探针和 1 个路由探针。

## 数据流

```
loader --> featurizer --> scorer --> positive
                                \--> negative
```

| 模块 | 入口函数 | 输入 | 输出 |
|------|----------|------|------|
| loader | `load_data(seed)` | `{seed: int}` | `{rows, n}` |
| featurizer | `extract_features(rows, n)` | `{rows, n}` | `{features}` |
| scorer | `score(features)` | `{features}` | `{score}` |
| positive | `branch_pos(score)` | `{score}` | `{label, score}` |
| negative | `branch_neg(score)` | `{score}` | `{label, score}` |

以 `seed=42` 运行时，scorer 输出 `score=0.64`：

- **断言探针** `$output.score >= 0.5` → 通过（0.64 ≥ 0.5）
- **路由探针** `$output.score >= 0.8` → 条件为假，记录 on_false 分支（negative）

> 注意：MVP 中路由探针仅**记录**分支决策，不改变数据流。positive 和 negative
> 都会正常执行并产出快照。

## 一键运行

```bash
cd examples/pipeline
python demo.py
```

脚本会依次执行 `sfa init` → `clean` → `extract` → `module add` ×5 → `pipe add` ×4 →
`probe add` ×2 → `run` → `observe` → `list` → `graph`，全程离线、无需 API key。

脚本可**重复运行**：每次开头先用 `sfa clean` 清空 `.sfa/` 生成物（保留 `sfa.yml`），
因此无需手动删除 `.sfa/`。

## 前置条件

- 已安装 `sfa` 命令（在仓库根目录执行 `pip install -e ".[dev]"`，或 `pipx install .`）。
  脚本优先调用 `sfa` 可执行文件，找不到时回退到 `python -m sfa`。

## 手动逐步运行

如需逐步理解每个命令，可参照 `demo.py` 中的调用序列手动执行，例如：

```bash
sfa init --target .
sfa extract --project .
sfa module add --name loader --entry load_data --project .
sfa pipe add loader featurizer --project .
sfa run --input input.json --project .
sfa observe --project .
sfa list --project .
sfa graph --project .
```

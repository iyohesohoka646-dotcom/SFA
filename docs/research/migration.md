# 科研模式与旧项目迁移

普通 `.py` 分析代码无需先变成端口图。选择项目目录、源码与科研解释器即可观察。`research.yaml` 保存可提交的配置，`.cdaf/research/` 保存运行证据。原 `flow.yaml`、源码、契约和探针保留，“旧版架构”仍可编辑端口流程。

```powershell
cdaf --json research migrate .\old-project .\research-project
cdaf --json research migrate .\old-project .\research-project --apply
```

第一条只预览，第二条写入独立的空目标目录。旧数据库只读，定义保留备份与摘要；已有非空目标拒绝覆盖。历史 ID 保留，分别标记 `legacy-sfa-json`、`legacy-port-flow`，科学值标记 `not_captured`。不能补出当时没有采集的矩阵、轴语义或精确源码版本。

| 入口 | 兼容行为 |
| --- | --- |
| `cdaf` | TTY 进入科研终端；非 TTY 显示帮助；`--json` 支持批处理 |
| `observe / research / models / terminal` | 科研观察、历史、共享模型配置与交互 |
| `cdaf studio` | 科研 Web；最后标签关闭后停止拥有的服务 |
| `serve` 或 `studio --background` | 持续服务，关闭查看器继续运行 |
| 原 `check/plan/run/context/generate/review` | 契约流程保留，不自动转换为科学溯源 |
| `sfa` | 当前 CLI 别名；`sfa legacy …`、`python -m sfa …` 保留原接口 |
| `shortcut / cdaf-studio` | 一个无终端的 Web 入口，兼容原用户目录 |

关闭拥有的服务会取消该服务启动的任务。独立 CLI 分析不属于查看窗口。回放读取历史，重新执行产生新运行 ID。

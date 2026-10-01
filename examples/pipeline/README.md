# 旧版 SFA 数据处理流水线

本示例保留旧版 `sfa` Python 模块与 `.sfa/` 格式，用于兼容和迁移验证。新工作台示例见 [data-pipeline](../data-pipeline)、[business-flow](../business-flow) 和 [nested-composite](../nested-composite)。

```text
loader → featurizer → scorer → positive
                         ↘ negative
```

在已安装本项目的环境中运行：

```console
cd examples/pipeline
python -X utf8 demo.py
```

脚本通过当前解释器执行 `python -m sfa`，依次初始化、扫描源码、定义模块/连线/探针、执行并观察结果，可重复运行。新版 `clean` 仅清理扫描缓存，保留架构、探针与历史记录；脚本复用已有定义，不再依靠删除定义重置项目。

旧 Router 只记录条件和假想目标，`positive`、`negative` 两个模块仍都会执行。迁移后对应 `branch_observer`；需要真实条件执行时，请在新模型中使用 Decision 和 guard。

旧命令可通过 `python -m sfa` 或 `sfa legacy` 使用。直接执行 `sfa` 是 `cdaf` 的兼容入口。迁移先运行 `cdaf migrate .` 预览，再通过 `--apply --destination PATH` 写入单独目录；原示例保留。

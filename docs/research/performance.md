# 科研采集性能记录

原始记录：[`research-sdk-performance.json`](../assets/research-sdk-performance.json)。同机 Windows、Python 3.11、NumPy，BLAS 单线程，固定随机输入，1536×1536 矩阵乘法。在独立进程中比较关闭、元数据、摘要和完整采集，每档三次；每次关闭采集的实际计算均超过 10 秒。

| 模式 | 中位耗时 | 相对关闭采集 |
| --- | ---: | ---: |
| 关闭 | 11.486 秒 | 基线 |
| metadata | 11.585 秒 | +0.86% |
| summary | 11.852 秒 | +3.18% |
| full | 14.100 秒 | +22.75% |

各次最终输出的 SHA-256 相同，采集未报错、未丢事件。默认摘要采集的进程峰值工作集约 114.3 MB，基线约 113.3 MB；完整采集另保存约 264.2 MB 产物，达到单运行预算后停止物化并记录原因。每个子进程退出时删除其临时基准产物，保留测量记录。

该结果验证当前显式 SDK 在这个 CPU 密集案例中的开销，没有证明任意脚本、自动插桩、慢消费者、浏览器或 GPU 的性能。全量采集的额外耗时单列，默认关闭。复现命令为 `python scripts/benchmark_research_capture.py`。

选定变量 `result` 的自动插桩另测三次：关闭中位 12.113 秒，自动摘要 12.575 秒，额外耗时约 3.81%；输出摘要相同，未丢事件。记录在 [`research-auto-performance.json`](../assets/research-auto-performance.json)，复现命令为 `python scripts/benchmark_research_capture.py --modes off auto_summary --output docs/assets/research-auto-performance.json`。它验证选定矩阵运算的自动观察开销，没有测试任意 Python 程序的每条语句。

旧工作台的本轮真实交互基线在 [`research-baseline.json`](../assets/research-baseline.json)：630 个逻辑模块折叠为 30 个节点时，加载与布局约 8.0 秒；请求上下文过程中改变节点，响应虽然成功却无法展示，且全局任务状态阻塞无关按钮。科研工作台重写后将使用独立的交互、流式观察和布局基准核对这些问题。

## 科研工作台与十分钟实时运行

[交互记录](../assets/research-workbench-performance.json)使用 1000 个逻辑变量、10000 条历史事件，画布最多 80 个可见节点。数值更新不改变拓扑；真实浏览器验收检查搜索、选择、详情与慢请求独立性。这是受控场景，不代表所有连接密度或数据类型。

两次同机 64×64 矩阵以目标 10 Hz 更新约 603 秒，浏览器每秒选择变量查看热图，没有强制垃圾回收。[对照](../assets/research-soak-comparison.json)、[改动前](../assets/research-soak-before-cache.json)与[改动后](../assets/research-soak.json)保留原始数据。

| 测量 | 改动前 | 历史索引只存元数据后 |
| --- | ---: | ---: |
| 点击至详情 p50 | 21.39 ms | 24.81 ms |
| 点击至详情 p95 | 36.92 ms | 62.86 ms |
| 最后两分钟 JS 堆中位数 | 59.08 MiB | 13.57 MiB |
| 两分钟窗口 JS 堆中位数 | 20.17 / 31.64 / 42.61 / 52.87 / 59.08 MiB | 9.01 / 11.23 / 11.78 / 13.38 / 13.57 MiB |

历史预览数组曾随事件积累；索引与时间线现在只缓存元数据，选中样例按版本读取。此修改减少了这段运行中的增长。同期验证与打包使机器负载不同，不能声称速度提升。后一次详情 p95 满足局部 250 ms 预算；点击至详情不能替代发布至显示的流式延迟，也不证明无限期稳定。

复现：`node scripts/soak_research.cjs 600`，需要当前构建、Windows Edge 与项目 `.venv`。该慢基准不混入快速测试数量。

## 实时显示延迟

`node scripts/measure_research_stream.cjs 60` 单独测量同机 64×64 矩阵、目标 10 Hz 的观察时间戳到选中版本详情就绪后两次动画帧。它包含采集合批、传输、SQLite、界面合批和详情请求；观察早于发布，因此比单纯发布到显示更保守。该夹具关闭探针，不能推断昂贵检查的延迟。

[改动前](../assets/research-stream-before.json)记录 561 个观察版本中的 503 个显示版本，p50/p95 为 192/256 ms，250 ms 预算检查失败。服务空轮询等待由 100 ms 缩为 50 ms、保留十秒心跳后，首次复测记录 563 个观察版本中的 530 个显示版本，p50/p95 为 160/229 ms。最终正确性修复后的[复测](../assets/research-stream-performance.json)记录 564 个观察版本中的 539 个显示版本，p50/p95 为 163/226 ms，检查通过。启动期间及合批未显示的版本单列；全部运行证据仍保存在本地。复测期间还有桌面打包负载，数值仅代表这次受控实测。

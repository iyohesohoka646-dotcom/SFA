# 科研探针协议 v1

探针接收数据描述符、脱敏且有界的样例、统计和参数，不持有分析进程的活对象。结果与执行状态分开；正常返回但 NaN 检查失败会保留两个事实。`ProbeResult` 使用 `pass/fail/error/skipped/unknown` 与独立精度 `exact/sampled/metadata_only`。

有限值探针仅在全部数值都检查过时报告全量通过。样本全为有限值但仍有未观察单元时返回未知；样本中的 NaN／Inf 或越界数值可以作为失败见证。方差和缺失比例的样本估计不能代替总体断言。形状和 dtype 直接使用实际对象元数据。

自定义插件实现 `protocol_version = 1` 和 `evaluate(context: ProbeContext) -> ProbeResult`，通过 `cdaf.research.probes` entry point 注册；显式启用后加载。也可在可信本地配置中调用 `registry.register("my.check", "my_package:MyProbe")`。示例 [`custom-probe.py`](../../examples/research/custom-probe.py) 无需修改核心即可接入。

`ProbeContext` 是冻结的结构，嵌套列表转换为元组、字典转换为只读映射。自定义探针运行在最多两个复用子进程中，使用有长度限制的严格 JSON 管道，不使用 pickle。启动和首次导入各限时 3 秒，求值默认 50 毫秒；超时结束对应进程，后续任务可恢复。待处理队列默认上限 16，拥塞产生明确的 skipped 结果。插件普通 stdout 重定向到丢弃的 stderr，避免污染事件通道。

进程隔离保护分析进程内存和响应，不是文件或网络沙箱。插件拥有用户进程通常的操作系统权限，仅启用可信插件；不会自动扫描并执行全部已安装插件。插件结果再次脱敏后才能写入证据和发送给客户端。

秩、条件数和特征值要求 `enable_expensive=true`，仅使用已经明确保存的完整 NumPy 数值产物。读取限定在授权证据目录，禁止 pickle；没有完整历史时返回未知，不使用最新活对象。计算在同一受限进程池中运行，超时与其他检查一致。

探针自身不控制执行。`control_action` 将结果交给单独策略：continue 不阻断；失败按配置暂停或取消；阻断检查发生 error／unknown 时暂停，让用户决定。运行服务在受控边界处理这些动作并记录控制事件，回看历史不会重新计算或触发控制。

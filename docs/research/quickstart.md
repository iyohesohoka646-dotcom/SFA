# 观察自己的科研脚本

安装版入口是 `cdaf studio`（浏览器）、Windows 桌面程序或 `cdaf terminal`（交互终端）。点击顶部文件名填写脚本与计算解释器，点击“导入解析”，在“探针台”配置呈现、检查和解读，再点击“运行”。矩阵、源码、计算关系、工具与智能助手各自拥有标签和可调整分屏。顶部“模型设置”配置模型；自动 harness 的实际发送与调用记录可查看。[工作台说明](workbench.md) · [发行验证](../release.md)。

核心可独立运行，无需浏览器或模型密钥。工具环境与计算环境可以分开；计算代理只依赖标准库，在 `--python` 指定的解释器中加载脚本所需的科研库。

```powershell
python -m pip install -e ".[research]"
cdaf --json observe .\analysis.py --python .\your-env\Scripts\python.exe --project . --capture summary
cdaf --json research runs --project .
cdaf --json research inspect <snapshot-id> --project .
cdaf research export <run-id> --project . --output evidence.json
```

可从 `src/contract_driven_ai_flow/templates/research-analysis/analysis.py` 开始；`--arg=--failure` 和 `--arg=nan` 会传给示例脚本。先运行成功案例，再运行带 NaN 的版本，对照真实变量、来源行和探针结果。退出码为成功 0、计算失败 1、配置错误 2、取消 130；断言失败与计算失败分别记录。

默认 `summary` 保留 shape、dtype、小样例与有精度标签的统计。`--capture metadata` 只保留元数据；`--capture full` 显式保存有界完整数据，表格完整采集还需安装 `.[tables]`。历史切片读取指定快照；未保存、缺失或过期时返回不可用，不会重新运行分析。完整产物单个默认 64 MiB、单运行 256 MiB，结束 7 天后可过期；摘要、事件和用户代码保留。

默认自动观察普通赋值和明确的原位修改。生成器、异步内部、反射、隐藏库内部写入等限制见 [instrumentation.md](instrumentation.md)。路径表示观测到的变量依赖或显式 SDK 关系；不声称逐元素因果证明。未知、设备和延迟对象默认只读取安全类型元数据。

发行数据插件用 `cdaf.research.adapters` 注册，安装到**计算解释器**后，用重复的 `--adapter <entrypoint-name>` 明确启用。探针插件用 `cdaf.research.probes` 注册并在独立工作进程内执行；配置见 [probe-api.md](probe-api.md)。两种插件都需显式选择，文件和网络权限仍属于用户。运行器协议 v1 统一私有 JSON 事件和边界控制；`RunnerRegistry` 注册执行适配器，首版内置 Python，其他语言需要实现该协议后接入。前端渲染接口随工作台固定。

本地 HTTP `/api/v1/research` 与 CLI 共用 `ResearchService`。事件 SSE 支持 `Last-Event-ID` 续接；CLI 启动的独立计算不依赖查看器连接。异常退出保留退出码与采集故障，服务恢复时将已退出的所有者标为中断，保留既有证据。

迁移先预览，目标必须是独立的空目录：

```powershell
cdaf --json research migrate .\old-project .\research-project
cdaf --json research migrate .\old-project .\research-project --apply
```

原 SFA JSON 快照与旧端口数据流记录保留原 ID 和语义，归入旧格式证据；旧文件不修改。迁移不能补出当时没有采集的矩阵、轴语义或精确源码版本。

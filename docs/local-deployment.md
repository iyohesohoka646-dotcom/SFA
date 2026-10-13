# 本地科研工作台

`cdaf studio` 启动并打开 Web 工作台。默认服务在最后一个标签关闭后宽限 3 秒再退出；刷新、多标签和保持真实连接的后台标签继续使用服务。尚未建立连接的启动租约最多等待 120 秒。连接依据真实 SSE 连接维护，不依赖后台页面的定时器。工作台提供“退出并停止”。

Windows 桌面外壳使用同一套界面，关闭窗口会取消并清理自己启动的服务及任务；重复启动聚焦已有窗口。连接已有持续服务时只借用它，关闭客户端不会终止借用的服务。独立 CLI 分析拥有自己的执行进程，可以在 Web／桌面关闭后继续。需要长时间执行的分析使用 `cdaf observe` 或显式后台服务。

## Python 安装与 Web

```powershell
python -m pip install ".[research]"
cdaf studio --project .\experiment
cdaf shortcut
```

普通用户不需要 Node.js、模型密钥或云账户。Python 3.11+ 安装路径携带已构建前端；`research` 选项包含首批 NumPy／pandas 案例依赖。其他数据类型通过明确启用的适配器接入，参见[适配器协议](research/adapter-api.md)。科研解释器在工作台中明确选择，计算环境与工具环境分开。

`cdaf shortcut` 生成一个 Scientific Dataflow Inspector 原生入口，绑定当前工具解释器；可以指定 `--directory PATH` 或 `--project PATH`。Windows 使用 `.lnk`，macOS 使用 `.command`，Linux 使用 `.desktop`。只清理这个包此前生成的两种旧启动／停止链接。移动工具环境后重新创建入口。

仓库的[启动工作台.cmd](../启动工作台.cmd) 仍可打开 Web；[停止工作台.cmd](../停止工作台.cmd) 作为旧入口保留。默认用户数据目录和 `CDAF_HOME` 保持兼容。无架构定义的普通目录可以直接启动科研界面；旧架构功能从“旧版架构”进入。

## 持续服务与端口

```powershell
cdaf serve --project .\experiment
cdaf studio --project .\experiment --status
cdaf studio --project .\experiment --stop
cdaf studio --project .\experiment --background
```

`serve` 和显式 `--background` 保留服务，关闭浏览器不停止它。默认选用 8765–8785 的空闲端口；`--port` 明确指定。被占用的端口会报错；不会替换其他监听程序。关闭先取消拥有的任务并落盘，最多等待 5 秒，再结束仍未响应的拥有进程。身份由目录、会话和当前启动确定，强制清理使用持有的进程句柄，防止误杀被复用的 PID。

## 桌面构建

`desktop/` 提供 Electron 外壳、后台控制和 Windows NSIS 安装器配置。安装器携带私有 Python 与 Chromium，工具服务无需依赖开发环境；科研脚本仍可选择另一个解释器。Electron 版本与构建依赖由 `desktop/package-lock.json` 固定；外壳较建议的 Tauri 更占空间，但能使用当前工具链进行窗口和安装验证。发行验证结果见[发行记录](release.md)。

开发窗口先运行 `npm ci --prefix desktop`，再执行 `npm start --prefix desktop -- --project PATH`；`CDAF_DESKTOP_PYTHON` 明确指定已安装本工具的运行时。缺少运行时显示可重试的启动错误。生产包禁用渲染器 Node 集成，隔离预加载脚本，只打开所属回环服务；不从网络加载插件脚本。

## 配置、证据与连接恢复

模型设置在顶部，终端使用 `/model`，批处理使用 `cdaf models`；选择相同项目目录时三种客户端共用配置。默认离线解释不发出模型请求。密钥只保存明确的环境变量或系统凭据库引用。解释发送范围可以先审查，样例须显式加入。

`.cdaf/studio.json` 保存本地管理会话，`.cdaf/studio.log` 保存诊断；科研运行及有界观察证据另行存储，不删除用户脚本或探针定义。重放不会重新执行脚本，重新运行会创建新记录。历史完整数据必须显式采集。

出现“127.0.0.1 拒绝连接”时，重新执行启动入口并等待就绪，使用入口自动打开的当前地址。不要依赖上一次的固定端口。服务绑定回环地址，并校验会话与来源。科研代码和显式启用的插件仍具有该用户的文件及网络权限；子进程隔离不构成操作系统沙箱。

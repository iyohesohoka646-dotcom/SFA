# 本地 Web UI 部署

安装后执行 `cdaf studio`，或双击仓库根目录的 [启动工作台.cmd](../启动工作台.cmd)。服务在后台启动，确认网页和认证 API 就绪后自动打开浏览器。关闭终端或浏览器后继续运行；重复启动复用已有服务。

在空目录启动时，首页是项目工作区：默认包含可运行的数据处理案例，可以新建空项目、选择另外两种模板，或注册已有 `flow.yaml` 目录。打开项目不会执行代码；在 Runs 中选择成功、失败样例后运行。在已有项目目录执行 `cdaf studio` 则直接打开该项目，`--workspace` 始终打开全部项目。

## 安装与快捷方式

需要 Python 3.11+。从这个版本的仓库或解压后的源码发行包安装：

```console
python -m pip install .
cdaf studio
cdaf shortcut
```

`cdaf shortcut` 创建原生桌面启动、停止快捷方式，绑定当前安装的 Python 环境。也可用 `--directory PATH` 指定快捷方式目录，`--project PATH` 绑定单个项目。Windows 使用 `.lnk`，macOS 使用 `.command`，Linux 使用 `.desktop`；后两者的桌面环境可能要求首次允许启动。移动或删除 Python 环境后需要重新创建快捷方式。

安装包还提供 `cdaf-studio` 应用入口，Windows 中通过无终端窗口的启动器运行。普通使用不需要 Node.js、API 密钥或云账户；首次安装依赖需要联网。Node.js 用于重建前端和可选 Archify 渲染器。功能分支已推送到 GitHub，并创建[草稿 PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1)；当前默认分支尚未合并，PyPI 尚未发布。

有 Git 时可直接安装该功能分支：

```console
python -m pip install "git+https://github.com/iyohesohoka646-dotcom/SFA.git@feat/contract-driven-ai-flow"
python -m contract_driven_ai_flow studio
python -m contract_driven_ai_flow shortcut
```

仓库中的双击入口优先使用项目 `.venv`，缺少环境或对应本地包时自动创建并安装。默认打开用户工作区，不写入仓库中的样例。Windows 工作区位于 LOCALAPPDATA 下的 ContractDrivenAIFlow，macOS 位于 ~/Library/Application Support/ContractDrivenAIFlow，Linux 位于 XDG_DATA_HOME 或 ~/.local/share 下的 contract-driven-ai-flow。`CDAF_HOME` 或 `--home PATH` 可明确指定位置。

## 生命周期与端口

```console
cdaf studio --workspace
cdaf studio --workspace --status
cdaf studio --workspace --stop
cdaf studio --project PATH
cdaf studio --project PATH --stop
cdaf studio --foreground
```

默认在 8765–8785 中选择空闲端口；`--port 8766` 指定端口，若被其他服务占用会明确报错。前台模式可用 Ctrl+C 停止。后台停止入口使用当前会话和目录身份确认服务，不按过期进程号终止其他程序；停止服务前会取消正在运行、排队或断点暂停的任务。不同项目的工作区子应用保留各自运行器和存储。

Windows 托管作业若禁止进程脱离，启动器保留无控制台后台运行，并遵守该宿主的作业生命周期；宿主结束整个作业时仍可能终止服务。普通桌面启动与关闭浏览器、终端的行为分别经过验证。

PowerShell 双击入口接受 `-Project PATH`、`-Port NUMBER`、`-WorkspaceHome PATH` 和 `-NoBrowser`。双击 [停止工作台.cmd](../停止工作台.cmd) 正常停止默认工作区。重启电脑后重新打开快捷方式即可；当前没有设置开机或登录自动启动。

## 功能与连接恢复

项目画布提供架构、运行、探针和变更审查；Project tools 提供执行计划、源码扫描、架构提案导入、集成导出、迁移、缓存与历史维护、安装诊断和命令目录。工作区与项目操作调用同一 Python 服务，具体对应关系见[Web/CLI 功能记录](web-cli-delivery.md)。

运行状态和会话保存在服务目录 `.cdaf/studio.json`，日志位于 `.cdaf/studio.log`。快捷方式错误另存 `.cdaf/launcher-error.txt`。这些文件与可提交的架构定义分开保存。

“拒绝连接”表示该端口没有监听服务。重新运行 `cdaf studio` 或打开快捷方式，等待就绪后使用自动打开的地址。身份验证过期时，重新启动入口会复用服务并打开当前有效会话；网页也提供重试和粘贴当前本地会话地址的入口。`cdaf doctor` 与网页 Installation 可检查安装和项目状态。

服务仅绑定回环地址。Python 模块进程继承当前用户的文件与网络权限。

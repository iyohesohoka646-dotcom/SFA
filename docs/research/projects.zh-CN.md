# Python 项目工作台

0.6 支持本地多文件 Python 科研项目，普通脚本与 `src/` 包布局共用相同的项目、运行和探针协议。Web 与桌面打开同一工作台；CLI 调用同一应用服务。

## 打开与运行

1. 启动桌面程序或 `cdaf studio --project PATH`。点击 **Open folder**，桌面版弹出系统文件夹选择器，网页版展开并聚焦路径输入。也可以展开 **Enter folder path**，输入后按 Enter 或 **Open project**。已打开的目录列在 **Recent**，点击即可重开；桌面支持依次按 Ctrl+K、Ctrl+O。首次只扫描与解析源码，文件错误单独显示，不执行程序。
2. 打开 **运行入口**，从候选中选择一个，或 **Add** 新建。Script 使用项目相对 `.py` 路径；Module 使用 `research_lab.main` 等模块名。
3. 保存名称、参数、工作目录与解释器引用。解释器路径和环境值在 **Advanced: machine references** 注册；项目配置只保存引用。`src/` 项目应先在所选环境安装项目，或明确设置自己的导入环境。
4. 点击 **运行**，查看任务和实际加载文件。运行结束后展开目录、文件和函数，双击变量打开对应证据。单击只选择；图上右键可定位源码或进入块，**Back** 返回。

对象默认显示所选运行中最近实际采集的值；未执行的静态最后一行不会成为最终值。源码、图、快照均关联运行时项目版本。切换到旧运行后查看旧源码；缺失归档显示错误，不替换成当前文件。

## 探针与数据

探针台分为选中对象、新探针和应用模板。自动数据视图是可编辑模板，每个有效呈现绑定生成独立视图。局部停用不影响其他对象；关闭标签不等于停用探针。

保存绑定不会计算。**执行探针** 和 **重新绘图** 使用选定运行的历史输入与当前探针配置，提交时冻结配置；它们不会重新执行项目入口。新增探针后无需重新计算已有完整输入。历史输入不完整时明确报错，补采集必须创建新运行。

上方范围可选整个项目、当前选择或已进入的当前块。计划冻结后，改变选择不改变正在运行的目标。目录、文件、函数与变量保留各自身份，同名变量不会串用。

## 智能修改

在模型设置配置服务，再在智能助手选择已有配置。初始上下文包含目录摘要、入口、范围和工具清单；后续按权限查询符号、引用、源码和证据。**上下文预览** 不调用模型。原始终端输出不自动加入上下文。

跨文件修改在修改审查中显示逐文件差异与验证记录。接受前复核所有文件摘要；冲突阻止整组应用。应用采用暂存、备份和恢复日志，恢复未完成时禁止运行及索引。回滚生成新提案。接受修改不会自动运行科研程序。

## 旧工作区与迁移

单文件工作区可继续使用 **Single-file workspace**，保持原扫描范围和历史记录。需要扩展时明确打开目录并配置项目入口。首次添加项目声明前保留原 `workbench.yaml.bak`；已有备份不会被覆盖。旧运行缺少项目版本时继续由兼容入口读取，不自动归属到新项目。

旧版探针配置先预览：

```powershell
cdaf --json workbench migrate-config --project PATH
cdaf --json workbench migrate-config --project PATH --apply
```

预览检查歧义；应用保留旧定义备份。迁移不会搬动或清除运行、快照与产物。升级前后的原安装数据清单另行核对。

## CLI

```powershell
cdaf --json workbench project open PATH
cdaf --json workbench project index --project PATH
cdaf --json workbench project entries --project PATH
cdaf --json workbench project entries --project PATH --save entries.json
cdaf --json workbench project plan --project PATH --entry main
cdaf --json workbench project run --project PATH --plan PLAN_ID
cdaf --json workbench project graph --project PATH --view data
```

`entries.json` 是运行配置数组，例如 `[{"id":"main","name":"Main","kind":"script","target":"main.py"}]`。批处理运行等待完成并返回明确退出码；交互 `/project run` 实时接收变量。Ctrl+C 取消所属任务。内嵌终端在项目目录启动，隐藏保留会话，结束会话和退出所属应用清理进程。

## 覆盖范围

首版覆盖本地同步 Python、多文件直接调用、普通及相对导入。动态分派、自定义加载器、异步与生成器可能形成部分覆盖；第三方源码和子进程内部不自动追踪。Notebook、多语言、多根与分布式执行未纳入本版。

大型项目按需读取，默认画布最多约 350 个可见单元，省略数量明确显示。索引在后台执行，修改一个文件复用未变文件。跨平台 CI 已保留；本机 Windows 验证、其他平台与真实外部模型效果分别记录在发行证据中。

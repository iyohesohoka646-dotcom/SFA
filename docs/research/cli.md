# 科研命令行与交互终端

`cdaf` 在交互终端中打开科研界面；管道中输出帮助。`cdaf --help` 查看批处理命令，`cdaf terminal --project PATH` 明确进入指定项目。终端只显示有界变量索引、摘要和事件；矩阵热图、表格及局部运算图在 Web 工作台中查看。

```text
/open "D:\experiments\analysis.py" --python "D:\experiments\.venv\Scripts\python.exe"
/run -- "an argument with spaces" ""
/vars covariance
/inspect SNAPSHOT_ID
/probe list
/probe preview SNAPSHOT_ID finite
/probe add finite X continue
/runs
/resume RUN_ID
/help
/quit
```

脚本路径和参数采用引号分隔，Windows 反斜杠保持原样，参数不交给系统 shell 执行。Web 的参数框也接受 JSON 字符串数组，可完整表达空参数和同时含两种引号的参数。选择科研解释器后，采集代理使用该环境已有的数据类型适配器；UI 服务的依赖留在工具环境。

运行和事件读取在后台进行。第一次 Ctrl+C 取消当前请求和当前运行；短时间内第二次 Ctrl+C 退出。取消后仍可输入 `/help`，退出会恢复终端屏幕与光标。事件续接使用已保存的序号并去重；`/resume` 查看原运行，重新 `/run` 创建新运行。变量缓存最多 1000 条，界面显示最近 200 条；事件日志最多 500 行。

## 模型与解释

Web、终端和批处理命令共用项目模型配置。默认 `offline / rules` 无需密钥，不发出模型请求。

```text
/model
/model search local
/model configure {"id":"local","protocol":"openai-compatible","base_url":"http://localhost:11434/v1","models":["your-model"],"default_model":"your-model","credential_ref":null}
/model test local
/model local your-model
/explain OPERATION_ID --context
/explain OPERATION_ID --provider offline --model rules
```

配置字段以 `cdaf models --help` 和工作台模型设置中的协议字段为准。远程服务只保存明确选择的环境变量或系统凭据库引用，拒绝把密钥文本写入项目配置。`/model test PROFILE` 进行发现／连接检查；加 `--inference` 才调用模型推理。终端不会读取其他工具的登录状态。

`/inspect` 选中快照后，`/explain` 可省略操作 ID。`--context` 先查看待发送范围，包括选中表达式、脱敏摘要与证据不足的标记；`--sample` 明确加入有界样例。解释区分规则生成和模型生成，并关联运行及操作。模型请求可取消，读超时遵循服务中的模型配置。

批处理入口仍可自动化使用：

```powershell
cdaf observe .\analysis.py --project .\experiment
cdaf research runs --project .\experiment
cdaf research explain OPERATION_ID --context --project .\experiment
cdaf models list --project .\experiment
```

`cdaf terminal --connect http://127.0.0.1:8765 --token-env CDAF_SESSION` 显式连接已有本地服务。令牌通过用户选择的环境变量提供；退出借用服务的终端只关闭该客户端。默认终端创建并管理自己的科研服务，关闭时清理它拥有的任务。HTTP 和 CLI 的运行操作使用同一个应用命令层。

## 参考与验证

交互分工参考 [Codex 的输入事件流](https://github.com/openai/codex/blob/6b4daafdb445340e5af66f067ad4057e6ed9fd81/codex-rs/tui/src/tui/event_stream.rs)，模型发现参考 [Kilo 模型选择器](https://github.com/Kilo-Org/kilocode/blob/dfb23a4e63e24e82a669a0eaf1e48e3c4ca21bec/packages/tui/src/component/dialog-model.tsx)，没有复制其代码。界面使用 Textual 后台工作机制，不在输入循环中执行计算。

真实 Windows PowerShell ConPTY 验证覆盖打开脚本、运行、离线模型选择、帮助、运行中取消、取消后输入及退出恢复，记录见 [终端验证数据](../assets/research-terminal-validation.json)。其他平台的交互终端仍须在对应系统验证。

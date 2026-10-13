# 多文件科研示例

这里有两个无外部依赖的夹具 flat-lab、src-lab，以及一个需要 NumPy 的矩阵示例 matrix-lab，用于真实跨文件采集。它们不需要密钥、网络或模型。

0.6 项目工作台可直接打开这些目录；保留的旧安装 0.5.4 不会自动获得新能力。[项目使用](../../../docs/research/projects.zh-CN.md)

matrix-lab 保存 Script 入口 main.py，运行后查看 prepare.build_dataset.X 与 compute.covariance.C。对 C 绑定 check.finite，再以 --nan 参数运行，可得到程序完成但数值检查失败的案例。默认自动视图、额外数据表与热图分别由有效探针提供。

## 目录结构

```
flat-lab/                 脚本入口
  main.py                 作者编写的入口，argparse，打印 str(score)
  prepare.py              确定性 random.Random(seed) 数据集
  compute.py              具名计算函数，含条件与循环
  checks.py               简单数值校验
src-lab/                  src 布局的包，模块入口
  pyproject.toml          setuptools 构建系统，无外部依赖
  src/research_lab/
    __init__.py           导入标记计数（不写副作用文件）
    main.py               python -m research_lab.main
    compute.py            数据集 + 计算
```

flat-lab 以脚本方式运行（main.py）；src-lab 以模块方式运行（research_lab.main）。两者结构相同：准备数据集、具名计算、简单校验，最后得到一个数值 score。

## 跨文件变量与作用域

X 被刻意复用。在 flat-lab/prepare.py 中它是 build_dataset 里的局部变量；在 flat-lab/compute.py 中它是 summarize 里另一个局部变量，src-lab/compute.py 同理。在两个文件里复用同一个名字是正常的 Python：每个绑定都有自己的词法作用域，项目运行会把它们保留为两个不同的快照（不同源文件、不同作用域），而不是相互覆盖。

## 成功与失败

* 正常路径：main.py 打印 str(score)；观测到的 score 快照与原生 stdout 完全一致。score 是真正的整数。
* 失败路径：--fail 让 compute.summarize 在数据集变量已被捕获之后抛出真实的 ValueError。原生进程以非零退出，运行被标记为失败，但它到达过的 compute.py 帧仍会被发布。这是真实异常，不是观测器植入的断言。

## 原生命令

完全按作者编写的方式运行示例（无机器绝对路径、无需安装）：

```powershell
# 脚本入口
python -X utf8 examples/research/projects/flat-lab/main.py
python -X utf8 examples/research/projects/flat-lab/main.py --fail

# 模块入口：该项目未安装，因此必须显式提供 PYTHONPATH
$env:PYTHONPATH = (Resolve-Path examples/research/projects/src-lab/src)
python -X utf8 -m research_lab.main
```

python -m research_lab.main 需要 research_lab 包位于导入路径上。该路径是真实编写的环境值（显式的 PYTHONPATH，或真正已安装的包）。索引会识别 src 布局并据此推导模块名用于规划，但解析器的 source_roots 设置不会悄悄改写 sys.path：导入仍只通过你编写的环境来解析。

## 公开应用 API

冻结作者编写的入口，执行真实程序，等待本次任务结束，再读取观测到的快照。符号引用（interpreter_ref、environment）留在仓库配置里；它们的私有值存放在宿主状态目录中，绝不进入仓库。

```python
from pathlib import Path
from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.workbench.models import RunConfiguration

host = Path('host-state')                                   # 私有环境/解释器引用
root = Path('examples/research/projects/flat-lab')
app = ProjectApplication(host)
try:
    project = app.open(root)                            # 登记项目并保存工作台元数据，不执行源码
    revision = app.index(project.id)                    # 绝不导入用户代码
    config = app.configuration(project.id)
    app.save_entries(                                   # 冻结作者编写的入口
        project.id,
        [RunConfiguration(id='main', name='Main', kind='script', target='main.py')],
        expected_revision=config.revision,
    )
    plan = app.plan(project.id, 'main', revision_id=revision.id)
    task = app.execute(project.id, plan.id)             # 真实启动
    done = app.workbench(project.id).jobs.wait(task.id, 30)  # 等待本次任务结束
    run = app.research(project.id).store.run(done.run_id)
    snapshots = app.research(project.id).store.snapshots(done.run_id, limit=1000)
finally:
    app.close()
```

对 src-lab 使用 kind=module、target=research_lab.main，并在 RunConfiguration 上设置 environment=["PYTHONPATH"]。PYTHONPATH 解析出的私有值只写入一次宿主状态，而不是仓库。

## 一次运行观测什么、不观测什么

* 导入与索引。打开项目会保存登记和工作台元数据，索引会保存解析结果；两者都不导入或运行源码。只有你保存并规划的那个入口会被执行。
* 捕获边界。只有经标准 source loader 加载、位于根内且被索引的模块会被追踪。标准库、第三方代码、非标准 loader 以及子进程都会作为明确的覆盖缺口上报，而不是被悄悄插桩。
* 执行 vs 质量。运行完成意味着程序跑完，并不保证数值在科学上正确。质量是另一个显式检查（见 checks.verify）。
* 冻结历史。一次计算会冻结内容寻址的清单，并在启动前立即校验摘要。源文件被改动后，原计算计划必须重新规划才能执行；已有历史证据仍绑定当时的源码版本，不受当前文件替换。
* 不需要模型。这些示例不发起任何模型调用。任何推理都是显式配置、彼此独立的关注点。

## 验收

tests/research/test_project_examples.py 会把每个夹具复制到隔离的临时目录（原始示例绝不被就地运行或写入），比较原生 stdout 与观测快照，检查真实失败路径，并确认跨文件来源。每个源夹具保持很小（每文件 <= 100 行）。

# 架构说明

当前实现为 Contract-Driven AI Flow 0.2.0：Python 模块化单体、Typer CLI、FastAPI 本地接口和 React Flow 工作台。完整说明见 [docs/architecture.md](docs/architecture.md)，命令见 [docs/cli.md](docs/cli.md)。

原始 SFA 的研究基线固定为 `c9a745e851d155b4c5fdede2d6cd2758c530e3c0`，旧源码保留在 `src/sfa/` 用于迁移。新语义模型由 `src/contract_driven_ai_flow/models.py` 定义；定义、视图、提案和运行证据分别管理。

已完成与待验证事项见 [IMPLEMENTATION.md](IMPLEMENTATION.md) 和 [发行验收](docs/release.md)。文档中的运行截图和案例由当前实现生成；历史愿景不作为能力证据。

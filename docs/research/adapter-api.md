# 科研数据适配器协议 v1

领域模型不限定 NumPy／pandas。`ValueDescriptor.kind` 和 `backend` 是可扩展的类型 ID；界面按 `capabilities` 判断是否提供预览、统计、切片或其他视图。未知对象只读取安全的类型名称，不调用属性、`repr`、`__array__` 或计算方法。

适配器实现 `protocol_version = 1`、唯一 `backend`，以及三个方法：

```python
class MyAdapter:
    protocol_version = 1
    backend = "my-package.tensor"

    def supports(self, value): ...  # 必须快速、不触发计算
    def describe(self, value): ...  # 返回 JSON 描述符
    def capture(self, value, policy): ...  # 返回 CaptureResult
```

描述符包括 `kind`、`backend`、`type_name`、可选 `shape/dtype/nbytes/device/axes/unit` 和 `capabilities`。能力名称可以扩展；标准名称为 `preview/statistics/slice/materialize/alias`。GPU、稀疏或延迟对象不能因声明能力就自动搬到 CPU、致密化或执行任务。用户显式设置相应策略后，插件才可提供这些操作。

使用 `AdapterRegistry.register(adapter)` 注册本地实例。发行插件可在 Python 包中声明：

```toml
[project.entry-points."cdaf.research.adapters"]
my-tensor = "my_package.adapters:MyAdapter"
```

仅调用 `registry.enable(["my-tensor"])` 后加载该插件；系统不会自动执行所有已安装插件。注册适配器与分析代码同进程，适配器作者负责保持只读和满足预算；此接口不提供文件或网络沙箱。独立探针协议用于隔离第三方检查代码。

[`custom-adapter.py`](../../examples/research/custom-adapter.py) 实现一种独立点云数据类型，不需修改核心即可接入。运行 `python examples/research/custom-adapter.py` 查看它产生的真实观察记录。

`CaptureResult` 含描述符、小样例、统计、精度、截断原因和脱敏字段。默认最多预览 1024 个单元、统计 4096 个元素；统计要注明 `sample_count/population_count/method/exact`。复杂数值以类型标签传输，NaN／Inf 不使用非法 JSON；未知对象内容标为不可用。适配器异常或协议错误产生 `capture.error`，分析继续且当前值降级为元数据。

历史样例在发布时复制，完整值仅在 `full` 策略及有产物目录时保存。数值产物采用禁止 pickle 的 `.npy`；表格产物依赖可选 PyArrow，使用 Arrow IPC 与类型化单元编码。切片读取指定观察的产物，缺失时返回不可用，不能读取最新活对象代替。默认完整产物上限为单个 64 MiB、单运行 256 MiB。

独立运行器可以产生同一版本的 `ObservationEvent`，无需依赖 Python 数据适配器。运行器使用 `RunnerRegistry`，发行入口组为 `cdaf.research.runners`；探针使用 `ProbeRegistry`，入口组为 `cdaf.research.probes`。两者均须显式启用，不会自动执行已安装插件。

前端渲染器协议 v1 位于 `web/src/research/renderer-registry.ts`，注册 `{protocolVersion: 1, id, supports(descriptor), Component}`。组件接收脱敏 `SnapshotRef`，通过描述符的 backend/kind/capabilities 选择视图；未知类型保留通用预览。`PointCloudView.tsx` 是独立点云适配器的完整示例，在 `main.tsx` 注册，浏览器验收使用真实 SDK 捕获的点云记录。新增渲染器需要重新构建前端；首版不从网络加载任意 JavaScript 插件。

GPU、稀疏、分布式、延迟对象与其他语言执行器当前尚无内置适配，注册接口为它们保留位置。插件应提供有界预览，明确说明是否发生设备传输、计算或物化，并注明观察覆盖范围。声明可扩展性不等于已验证这些后端。

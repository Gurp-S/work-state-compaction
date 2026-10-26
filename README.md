# WSC

Work State Compaction。给长期运行的 coding agent 做上下文压缩的 Python 组件。独立进程内库，旁路接入，默认关闭。

压缩最容易出的问题不是丢信息，而是"看起来接上了，实际接错了"。文件 V1 通过测试，改成 V2 后还没验证，压缩完只剩一句"文件已修改，测试通过"——字都是真的，版本对应关系没了，模型据此认为 V2 已验证。WSC 把压缩当成一次可核对的发布，而不是一次改写文本。

## 工作方式

一次压缩的输入固定成快照，输出是一份带来源的候选上下文，由宿主原子安装后才推进折叠位置。

- **来源**：事件按原样入库，重复投递不产生新事件；工具调用与结果必须配对，缺一半拒绝导出
- **快照**：绑定会话、工作区、代次、控制版本、理解版本和来源序号，每次使用前重新校验
- **选材**：由调用方的模型决定，组件只负责把选择绑到字节上（范围、内容哈希、唯一匹配）
- **预算**：按字节算必留内容的下界，超了在模型调用和记账之前拒绝
- **发布**：写盘只是 `ready`，宿主返回持久回执才是 `confirmed`；结果未知走对账，不重发
- **证据**：授权检查加精确字节读取，部分哈希、对象哈希、观察时间、完整性分开报

组件不判断语义对错，不调用模型，不替宿主执行任务，不伪造安装回执。宿主如果没有原子安装和持久查询能力，就只能停在导出边界。

## 安装

Python 3.11 以上，运行时只用标准库。

```bash
python -m pip install --no-deps .
```

## 用法

```python
from wsc import WSC, Store, Selection, Understanding
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.callback import CallbackHost

core = WSC(
    Store(db_path, session_id=session_id, workspace=workspace),
    access=current_source_permission,      # 宿主提供的授权检查
)

adapter = CodexCheckpointAdapter()
core.ingest(adapter.import_items(native_items, thread_id=native_thread_id))
core.presented(request_id, presented_source_ids, receiver=actual_receiver)

snapshot = core.capture(cut=source_boundary)
view = core.prepare(snapshot, Selection(), producer=model_output_identity)

operation = core.stage(view, directory=export_directory, adapter=adapter)
host = CallbackHost(commit=atomic_host_install, lookup=durable_host_lookup)
receipt = core.install(operation, host)
```

选材也可以交给模型：`core.generate(snapshot, generator, producer=..., limits=...)`。generator 收到公开材料，返回 `Generated(Selection(...), Usage(...))`。组件不带供应商、不带提示词、不读密钥。

CLI 每条命令都显式绑定 `--db`、`--session`、`--workspace`，不会去猜或改现有会话：

```bash
wsc --db state.db --session sample --workspace . import-native --input canonical-state.json
wsc --db state.db --session sample --workspace . prepare --selection selection.json --producer existing-model-output
wsc --db state.db --session sample --workspace . export --view VIEW_ID --directory checkpoint-output
wsc --db state.db --session sample --workspace . status
```

## 状态

仍在逐步实验中，暂不建议直接接生产链路。

## License

MIT

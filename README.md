# WSC

Work State Compaction。给长期运行的 coding agent 做上下文压缩的 Python 组件。独立进程内库，旁路接入，默认关闭。

## 问题

Agent 跑得久了，历史一定放不下，harness 必须挑一部分塞进上下文。这一步很容易把信息压成"看起来对"的样子。

比如文件 V1 跑过测试并通过，之后改成 V2 但没验证。压缩后剩一句"文件已修改，测试通过"。每个字都是真的，但"测试通过"对应哪个版本没了。模型读到的结论是 V2 已验证，接着就按这个结论往下走。

记录没丢，丢的是区别。WSC 关心的是压缩之后模型还能不能做出正确的下一步，而不是压缩率有多高。

## 设计

压缩的产物不是一段摘要文本，而是一份带来源、可核对、可回滚的上下文快照。围绕这个判断，代码里有六个概念。

**Source。** 一条原生事件：消息、工具调用、工具结果、opaque 项。按原样入库，同一 id 重复投递不会产生新事件，一个批次在一个事务里提交。工具调用和结果靠 `(call_id, kind)` 唯一索引配对，缺一半的直接拒绝导出，不完整的东西不许进入压缩。opaque 项原样归档，不尝试解密，也不进热上下文。

**Snapshot。** 一次压缩的输入被固定成快照，绑定 session、workspace、generation、control_epoch、understanding_epoch、cut 和来源摘要。`cut` 是来源序号，不是压缩后数组的下标。快照每次使用都重新校验，前缀变了就拒绝，所以不会出现"用旧材料配上新历史"。

**Understanding。** 模型明确说出来的判断，带来源、类别、适用范围和版本号。修订要带期望版本（CAS），并发改不会静默覆盖。系统允许存没有来源的假设，但不会把它升级成事实，`semantic_status` 永远是 `unverified`。

**Selection。** 选什么由调用方的模型决定。核心不做关键词排名，也不内置摘要提示词。三种前端（原文引用、字符区间、精确片段）只负责把模型的选择绑到字节上：算范围、算哈希、校验唯一匹配。模型改写、来源对不上、路径已经变了，一律返回事实状态，不修补、不猜。

**View。** 候选上下文。生成前先算必留的 user/system/developer 消息和视图骨架的字节下界，超了就直接拒绝，这次生成连记账都不进。全程按字节算，不按 token 猜，真实容量由宿主按实际请求判断。

**Publication。** 候选写盘只是 `ready`，不等于安装。`install` 时宿主在同一个同步边界里检查代次、控制版本、容量和在途工具，返回持久回执；只有 `confirmed` 才推进折叠游标。响应丢了走 `reconcile`，不重发。`lookup` 返回 `None` 表示结果未知，不表示没执行。

一次压缩的路径：

```
events -> snapshot -> selection -> view -> stage -> install -> confirm -> cursor
```

配套的两件事。证据访问单独做一层：`read` 做授权检查和精确字节读取，部分哈希、对象哈希、观察时间、完整性分开报；引用可以带资源哈希去查当前位置，只在唯一匹配时给行号。用量单独记一本账：调用发出前记账，失败、超时、没回执都留着，没报的用量记 `null`，汇总分成已知和未知两类。

边界也说清楚。WSC 不判断语义对错，不调用模型，不替宿主执行任务，不伪造安装回执。宿主如果没有原子安装和持久查询能力，就只能停在导出边界。`off` 模式不建库、不调 factory、不改传进来的上下文对象。

## 用法

Python 3.11 以上，运行时只用标准库。

```bash
python -m pip install --no-deps .
```

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
view = core.prepare(
    snapshot,
    Selection(new_understandings=(Understanding(
        text=explicit_model_statement,
        kind="diagnosis",
        sources=statement_source_ids,
        scope=known_scope,
    ),)),
    producer=model_output_identity,
)

operation = core.stage(view, directory=export_directory, adapter=adapter)
host = CallbackHost(commit=atomic_host_install, lookup=durable_host_lookup)
receipt = core.install(operation, host)
```

需要模型产出选材时用 `core.generate(snapshot, generator, producer=..., limits=...)`。generator 收到公开材料，返回 `Generated(Selection(...), Usage(...))`。组件不带供应商、不带提示词、不读密钥。`JsonCommandGenerator(argv)` 提供 stdin/stdout 的 JSON 传输，不经 shell。

CLI 每条命令都显式绑定 `--db`、`--session`、`--workspace`，不会去猜或改现有会话：

```bash
wsc --db state.db --session sample --workspace . import-native --input canonical-state.json
wsc --db state.db --session sample --workspace . presented --receipt presentation.json
wsc --db state.db --session sample --workspace . prepare --selection selection.json --producer existing-model-output
wsc --db state.db --session sample --workspace . export --view VIEW_ID --directory checkpoint-output
wsc --db state.db --session sample --workspace . status
```

## 现在到哪了

组件本身可用：来源绑定、快照校验、三种选材前端、字节预算、发布与对账、证据访问、用量账本都实现完了，430 条测试通过（`python -m unittest discover -s tests`）。

跑过的验证：

- 46 条原生事件回放往返一致，含 9 对工具调用/结果、16 条 opaque，原始角色和顺序保留，新增模型调用 0
- B/C 两臂各 18 项具名检查通过，产物相同，C 非缓存输入少 49%
- 同一会话的持久 PowerShell 在自动压缩后仍可访问，PID、nonce、心跳一致
- 原 S2/S3 请求在同一会话内自动压缩两次后正常交付，通过 17 项独立验收

还没证明的：

- 每个成功任务的总成本。目前只测到局部上下文体积下降
- WSC 的语义摘要比原生好。C 臂的摘要是原生内部压缩生成的，不算 WSC 的功劳
- 通用缺口识别。现在没有任何机制能自动判断模型缺了什么信息
- 长期稳定性。五个应用任务各三轮没跑完
- 调度收益和 WSC 增量。缺同阈值的原生诊断对照，分不清是压缩更早还是管理更好

已知限制：Codex 适配器只做显式检查点导出和恢复，没有透明原位替换；全来源核对的工作量跟历史规模相关，大规模多轮压缩的存储和延迟优势没验证；跨目录复用原生压缩状态不可靠，2026-10-23 的候选在正式 C 臂失败，没设成默认。

## 目录

```
src/wsc/      组件源码，约 2.3k 行
tests/        430 条契约测试
experiments/  旁路实验驱动与结果
reviews/      每轮决策、反例和止损记录
validation/   逐轮验证证据
benchmarks/   任务集与评分口径
```

`reviews/` 是决策日志，每轮都写了为什么改、证据是什么、哪里失败、为什么停。看代码之前先翻它。

## License

MIT

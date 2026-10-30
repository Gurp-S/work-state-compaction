# 统一上下文生命周期与宿主旁路 v1

2026-10-30。按用户确认的方向，先统一来源与外置工具结果，再共同接入折叠、发布及恢复。没有增加模型摘要层，没有恢复暂停的付费研究。

## 实现与职责

新增ContextRuntime是显式启用的宿主维护层。核心仍负责不可变来源、原子候选、发布游标和回执；宿主负责捕获真实工具结果、记录实际呈现、实际请求容量、触发时机、安装和调用执行；模型仍决定语义选材、理解与补证。

三层表示已经接成一条路径：当前工具结果的有界视图；折叠检查点中的来源入口、工具结果视图及模型明确保留的理解/片段；完整原始事件与外置文本。层数不增加模型调用次数。控制消息不按时间自动失效，模型理解仍带来源、scope和CAS版本，概览不会回写为原文。

本层不执行或重试任务工具。宿主已有执行器产生结果后调用record_tool_result；写入失败可重投同一事实，不能借此重新执行工具。capture/prepare/stage/install/reconcile复用核心协议，不建第二套发布状态机。

## 一套查询，两种对象

宿主注册一个WSCContext工具，替代在新接入路径同时暴露WSCSource与WSCResult：

|引用|读取内容|坐标|
|---|---|---|
|source:sN|冻结前缀中的原生产者公开文本|unicode_codepoints|
|result:rN|绑定原来源的完整外置工具文本|utf8_bytes|
|source:* 的find|绑定来源前缀的字面匹配|source_index游标|
|result:rN 的read_lines|原文起始行与字节分页|lines起点、next_offset字节|
|result:rN 的json_pointer|原文严格JSON字段|RFC6901|

read/find需要明确units，错误坐标返回事实状态，不猜测或暗中转换。describe给出可查询的关联引用。相同API既可读取原来源，也可读取外置文本，但这不是两个可绕过彼此权限的后门。

每个外置引用绑定会话、工作区、来源数据库、结果存储根、原调用ID、原来源序号/摘要、原文哈希和结果元数据。逐条原文与调用核对后才关联，不批量猜测旧rID来源。跨工作区借用结果库、换根目录、改来源序号、元数据或正文均不静默修补。

原来源和外置结果两边授权都适用，包含source:*搜索；结果超出旧快照cut不可查询。新快照能保留旧引用，不把旧事实升级成当前适用的判断。已交付信息不能被倒退撤回；回调原样重放也不被称为新的权限观察。

## 连续折叠与发布

1. observe保存原始事件；record_tool_result保存完整正文、关联来源、记录将要呈现的视图。两库是显式顺序提交，不冒充跨库原子事务；部分成功只允许重投记录，不重执行工具。
2. 工具返回不自动调用presented。宿主确认内容确已进入相应请求后，显式报告呈现回执；缺失时原安全边界照常拒绝capture。
3. material给选材调用方提供带representation标记的视图和原文入口，避免把大工具原文无条件重新塞回选材输入。此层没有内置模型或prompt；宿主使用自己的模型调用、预算与用量账本。不能改用旧core.generate而假称其输入已采用本层投影。
4. prepare显式采用context_source_refs_v1。选中的工具来源保存引用及摘要校验，原文和payload不改；需要精确内容时仍用原文片段。控制和消息原样保留，预算超限照常拒绝。
5. ContextCheckpointAdapter恢复原始来源后验证，并生成新上下文视图。尾部只对已登记、已绑定的纯文本工具结果采用已记录视图，调用ID、调用输入和非文本/控制材料不擅改。
6. stage只是ready，cursor不推进。宿主持久确认后才折叠；回执丢失用原reconcile，不重发安装或任务工具。已确认提交不因后来权限变化变成“没安装”。

ContextRuntime.validate_package核对额外恢复材料，install在首次提交前调用它。真实宿主仍须在自己的同步安装边界内完成必要检查；此旁路预检不是额外原子性或跨库事务保证。对账承认已发生的提交，不重新把它当首次候选准入。

原始事件仍完整保存在WSC数据库，文本也在外置存储；尚未用blob引用替换原始事件格式。因此有重复持久化成本。关联查询流式校验原事件TEXT，避免每页完整解码巨大JSON，但仍扫描原事件字节，不宣称这部分I/O免费。当前主要减少模型可见重复正文，不是已证明存储或主机性能最优。

## 原生宿主接入

experiments/native_context_recovery.py提供open_context_receiver：注册单个WSCContext，接入已有execute_stage回调，保留原容量/系统准入要求。请求重放按thread、turn、call绑定；跨轮相同本地call ID是新请求，改参数重放拒绝，缓存和trace有界。advance更新读取快照，但不重置ContextRuntime的总查询预算。

Windows和普通同路径宿主沿用原工作区核对。Linux/work/actor通过ContextWorkspace证明对应宿主actor-root/actor：新随机标记由真实原生命令读取并核对实际cwd；校验不改WSC Store.workspace，也不将客体路径交给Windows Path.resolve猜测。线程、进程、cwd、标记或宿主工作区变化均在读取前拒绝。标记是受信宿主的挂载一致性验证，不是抵抗任意宿主管理员的密码学证明。

只安装这一个查询入口，不能同时把可绕过来源授权的旧结果owner API注册给模型。低层API保留兼容用途，本层只约束经此接入的模型请求。

## 检查与证据

最终相关检查58项通过：新上下文生命周期14项、原生接入契约6项、工具外置23项、既有投影3项、Indexed检查点3项、既有任务恢复9项。不是全项目测试。

六次离线折叠验证：安装后generation/cursor推进，旧引用仍可读，理解CAS版本递增，查询预算不随快照刷新重置，控制不自动过期。使用已有SQLite故障注入宿主，明确不当作原生持久安装或模型任务连续性证明。

新增发现并治本修复重复正文回放：原实现对已存在call返回prior=None，导致第一次是去重引用、重投却变回正文概览，破坏交付幂等性。现在只选该调用首次提交时之前的同正文记录，后来调用不能改变回放。先红后绿记录在duplicate-body-before.json和stable-replay-after.json。

实际同版本Linux原生无模型接入：工具schema注册、真实工作区标记、真实command/exec生产者、视图注入原生历史和私有存储不可读通过。生产者公开正文68890字节，完整视图1875字节。恢复分派使用明确标记的脚本回调，不是模型发出的查询；呈现回执是离线fixture授予，不是假称模型已看过。实际模型回查、实际模型请求、原生检查点原子安装、Token净收益均未验证。

首轮native v1因验证脚本错误要求整条payload无原生附加字段而失败。复用既有import_evidence后，允许声明过的传输ID/元数据追加，正文、调用ID及输入字段逐项不变；v1错误、原轨迹和执行源码保留。v3在最后代码改动后重新冻结当前全部WSC源码再通过，无模型。

目录：D:/agent-task-runs/wsc-context-lifecycle-checks-20261030-v1；D:/agent-task-runs/wsc-native-context-port-20261030-v1/v2/v3。前者保存相关检查、回放先红后绿和最终清单；v3保存实际schema、映射、生产者、注入校验、脚本回调及私有读探针。WSL已终止，没有留后台任务。

## 接入示意

```python
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultPolicy, ToolText

runtime = ContextRuntime(core, result_store,
                         policy=ResultPolicy(enabled=True))
runtime.observe([original_call_event])
view = runtime.record_tool_result(original_result_event,
    ToolText(original_text, kind="terminal_log", exit_code=exit_code))
# 宿主把view作为该工具的模型可见结果，保留其他包络。
# 实际请求呈现确认后：
runtime.presented(request_id, [original_result_event.id], receiver=receiver_id)
snapshot = runtime.capture()
query_tool = runtime.query_tool(snapshot)
# 宿主注册query_tool.definition()并分派query_tool.call(arguments)。
# caller_selection仍由调用方模型提供。
view_id = runtime.prepare(snapshot, caller_selection, producer=producer_id)
# 适配器由调用方给出：core 层不 import adapters，依赖方向由契约测试守住。
from wsc.adapters.context import ContextCheckpointAdapter
operation = runtime.stage(view_id, directory=checkpoint_directory,
                          adapter=ContextCheckpointAdapter(runtime))
receipt = runtime.install(operation, atomic_durable_host)
```

独立部件现在可共同接入宿主旁路，不默认开启GUI/DSH/原生内置工具透明截获，不引入自动LLM分层摘要。当前尚未解决无限历史控制消息预算、模型何时补证及真实任务收益；这些不能由离线折叠检查冒充已达成。

下一步补齐实际模型请求的呈现/恢复闭环、任务运行时和提供方连接，在既定成本边界内验证真实输入与任务结果。原研究仍暂停，旧B/C成功与失败不重跑、不改分。

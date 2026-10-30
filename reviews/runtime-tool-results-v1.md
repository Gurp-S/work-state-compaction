# 工具大结果外置与按类型概览 v1

2026-10-30。独立旁路已实现，原B/C研究仍按用户要求暂停。没有调用模型、模型评分或重跑原比较；不把本次功能验证记成WSC已经优于原生。

## 已实现的运行路径

工具执行一次 → ToolText完整正文与执行元数据 → RuntimeResults.call/acall → 完整UTF-8文本持久化 → 类型化概览或正文去重 → 计算最终紧凑JSON大小 → 返回概览及短结果ID。

这是真正可供宿主在工具返回后调用的包装器，不是改已经完成的日志。独立CLI也可运行。它没有自动安装原生Codex内置工具钩子，也没有修改XEYO/DSH默认工具链；接入宿主时必须只把包装器返回的视图送入模型，不能同时再发送原始大正文。非文本/多模态包络由宿主保持，不在本接口中隐式转换。

调用方明确传入可信类型；未知内容用unknown。ToolText.text是完整的生产者文本，不做换行归一后再落盘。已有stdout/stderr分离的工具由宿主保留其包络或分别接入，本库不猜测、合并或丢弃未传入的数据。

## 七类策略

|策略|本入口的适用条件与行为|
|---|---|
|strip_noise_lines|仅terminal_log、stack、test、build；保守处理SGR颜色与CRLF，不删除INFO/错误/pytest行，不猜测独立CR的意义|
|collapse_stack|仅明确stack类型，复用相同相邻行折叠，附重复次数|
|diff_digest|仅明确diff类型，复用现有差异形状概览；完整补丁仍在原文中|
|dedupe_identical|完整原文相同才复用正文对象；每次调用单独结果ID、执行状态和时间，不声称两次执行等价|
|dedupe_reads|源码/文档读取的path、version、range均已知且相同，正文也相同才折叠；新版本不覆盖旧版本|
|outline_json|严格JSON解析后给有界结构、字段数、长度和少量样例；table支持JSON形式表格，其他表格保守回退文本预览|
|truncate_head_tail|受限头尾预览，明确标记中间省略，最终计算JSON转义、规则和引用后的完整体积|

不是旧七条规则无条件串行全开。重复键、NaN、过深或超解析上限的JSON不会被伪造成有效结构；源码和文档不走终端清理。语义保真不由原文可回查自动保证，概览是显式不完整视图。

退出码、超时、调用方status、source、facts、observed_at单独保留。execution_status是机械结果，例如nonzero_exit或timeout，不由exit=0推断整个任务成功。facts/source快照复制，宿主后续修改原字典不会改写旧视图。

## 外置、恢复与资源边界

- 每会话一个绑定的SQLite索引；原文对象为内容哈希命名的.txt。数据库保存各调用身份和元数据，相同正文只存一份对象。
- 文件先完整写入并同步，再提交索引。对象不覆盖；进程中断留下的未登记同哈希文件只有逐块验证完全一致后才对账纳入。
- 写入失败、已有对象损坏、逻辑额度不足或不能形成更小的有界概览时，保留原正文并返回事实状态，不发布死引用。宿主仍负责最终上下文容量准入；回退原文不是容量已经合格。
- 原文查询校验所读块，不为8KiB分页每次完整读取超大文件。行索引有一致性哈希。授权在读取前及返回前检查；内容、索引损坏和权限撤销不会返回假原文。
- 不自动清理有引用的旧结果，不把旧版本当成无用内容删除。一致性校验不是抵抗任意数据库写入者的签名机制。
- 当前接收已形成的Unicode文本，以小块UTF-8编码写盘，没有第二份完整编码/序列化副本。它尚未接管子进程stdout流，所以不宣称消除了上游工具自身的完整缓冲或具有硬RAM上限。

默认：超过32KiB才处理，完整概览JSON上限2KiB；单对象128MiB，已登记去重对象逻辑量512MiB；完整转换及JSON解析输入各8MiB，字面搜索每页最多扫描16MiB。临时文件、崩溃孤儿、SQLite和日志不计入该逻辑量，它不是物理磁盘硬配额。超过完整转换上限时用有界预览与原文入口，不对超大堆栈整段split。阈值可配置。

## 查询协议

ResultQueryTool提供WSCResult工具定义和分派：

- read：UTF-8字节offset及limit，最多32768字节；不修补落在字符中间的offset。
- read_lines：1-based起始行，按字节上限分页，以LF为行分隔、保留CRLF原字节；返回next_offset供续读。
- find：精确字面搜索，跨块可匹配，最多8条位置，返回覆盖完成状态及下一游标。
- json_pointer：RFC6901精确字段读取，保留false/null/数值类型；超解析或返回限额报事实状态，可改用原文分页。

查询结果recovery=True，即使超过外置阈值也不再次摘要。工具默认每实例64次调用、返回紧凑JSON最多32768字节；过大时返回限额状态，不假装给出了完整原文。宿主按会话绑定实例及授权回调，不能让模型选择任意root或session。

## Python接入

```python
from wsc.tool_results import (
    ResultStore, RuntimeResults, ResultPolicy, ToolText, ResultQueryTool,
)

store = ResultStore("./tool-result-data", session="session-1")
results = RuntimeResults(store, policy=ResultPolicy(enabled=True))

def wrapped_tool():
    result = actual_tool()  # 宿主已有工具；只执行一次
    return ToolText(
        result.text, kind="terminal_log",
        status=result.status, exit_code=result.exit_code,
    )

model_view = results.call("unique-tool-call-id", wrapped_tool)
query_tool = ResultQueryTool(results)
definition = query_tool.definition()  # 宿主注册WSCResult
query_result = query_tool.call({
    "operation": "read", "result_id": model_view["result_id"], "limit": 4096,
})
query_view = results.present("unique-query-call-id", query_result)
```

仅external=True的结果具有result_id；小结果、恢复结果、user/system/developer及关闭策略保持原文。SDK默认策略关闭，显式enabled=True才启用。授权回调签名为(session, result_id, "read")；CLI是本地owner入口，不提供多租户授权。

## CLI

安装当前包后有wsc-results入口；未安装可在设置PYTHONPATH=wsc/src后用py -3.11 -m wsc.tool_results.cli。显式使用这个独立CLI即选择启用，不改变原wsc检查点CLI。

```text
wsc-results --root ./tool-result-data --session session-1 present --input output.txt --call-id call-1 --kind json --exit-code 0
wsc-results --root ./tool-result-data --session session-1 read --id r1 --offset 0 --limit 4096
wsc-results --root ./tool-result-data --session session-1 find --id r1 --literal target
wsc-results --root ./tool-result-data --session session-1 json-pointer --id r1 --pointer /rows/2048/id
```

## 验证结果

22项针对性检查通过，覆盖七类策略、同步/异步执行一次、中文/emoji/CRLF原文往返、源码不误清理、旧版本不覆盖、身份冲突、授权撤销、损坏、额度和写盘故障、孤儿对象对账、跨块搜索、行范围、JSON字段类型及转义、过大查询不再摘要、超大输入跳过整段转换。

一次真实本地生产者进程生成835417字节JSON正文，完整概览反馈1160字节；JSON精确查询得到rows/2048/id=2048，库和CLI结果一致。另用同一72000字节CRLF文本对照旧清理函数：旧视图2字节且正文丢失，新入口预览保留正文、完整原文分页往返相同。旧规则代码未改，仅新旁路避开该错误。

这是机制演示，不是实际模型Token节省率、真实任务质量或与原生的收益对照；没有LLM调用。示例输入输出和费用未混入原B/C成绩。

另有链接后损坏注入反例：原实现会发布指向损坏文件的概览，现改为安装后的完整逐块重读校验，修复前失败、修复后通过；before/after日志保留。

开发时保留了两类早期失败记录：概览未计JSON转义后预算而回退原文，后改为按最终JSON收紧；查询测试请求32768原文而超默认JSON返回限额，该拒绝行为正确，测试改为独立验证默认拒绝与显式更高限额下的恢复豁免，没有扩大默认限额。

证据：D:/agent-task-runs/wsc-runtime-tool-results-20261030-v1和wsc-runtime-tool-results-demo-20261030-v1。入口validation/demo_runtime_tool_results.py输出独占创建；功能检查命令为py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_runtime_tool_results.py -v。没有跑无关全项目测试。

下一步是将这一个端口接入选定宿主的真实工具返回链，再做实际输入与恢复成本检查；不能把新增SDK和CLI等同于原生Codex代码模式的透明结果替换已解决。原研究保持暂停。

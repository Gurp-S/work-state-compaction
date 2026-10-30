# 原生运行时去噪接入口资格：普通文本可替换，当前代码模式不通过

2026-10-29。使用当前codex-cli 0.165.0-alpha.1.2及独立CODEX_HOME，本地脚本模拟Responses服务器，实际启动原生CLI和PowerShell工具。没有调用任何LLM，没有修改全局配置，没有重跑旧B/C，没有认领新增付费预算。这不是模型质量、压缩收益或真实任务续接实验。

## 得到的决定性证据

|探针|真实命令结果|下一次真实请求中工具结果|结论|
|---|---|---|---|
|v8，代码模式嵌套exec_command|退出0、原文已落盘|脚本promise正常返回，输出仍为完整原文|不能靠这个钩子实现当前代码模式的透明去噪|
|v9，普通exec_command|退出0、原文已落盘|原文被指定反馈替换，call_id相同|普通文本替换路径成立|
|v10，普通exec_command失败|退出1、原文已落盘|仍被指定反馈替换|这个钩子形状不足以安全区分失败|

三次hook输入的tool_response都是纯字符串，未携带退出码；命令执行事件中则可观察到真实退出码0/0/1。代码模式的内部tool_use_id也不同于外层exec的call_id，不能直接按外层ID绑定。不能用文本中是否出现error来补这个缺口。

v8的下一请求中，结构化返回精确为promise_resolved=true、result.exit_code=0、result.output等于原始CRLF文本。v9/v10的function_call_output则精确等于固定反馈值。判断基于预设协议字段与逐值断言，不是关键词评分，也不通过模型判断语义。

## 调查过程及保留的失败

v1未启用代码模式却发送custom exec，原生拒绝；v2隔离环境的workspace-write命令被执行策略拦下；v3改为仅含固定无害命令的danger-full-access接口夹具，工具可执行。v4补显式config层，v5移除matcher、v6启用代码模式、v7增加SessionStart对照，仍未执行钩子。hooks/list确认配置已发现、启用、无解析错误。

最终v8使用commandWindows中的PowerShell调用操作符后，SessionStart和PostToolUse均实际运行。此前问题是Windows钩子命令调用形式，不能推断原生不支持hooks。v9/v10保持正确调用形式，分别验证普通成功/失败工具路径。全部十次本地协议夹具均保留；不是十次付费实验。没有把CLI退出0当成接入通过。

仅对已审查的隔离hooks使用单次trust bypass，未信任或启动用户的其他钩子。v1中原生插件缓存产生未授权的远端元数据请求，后续显式关闭plugins；模型请求始终仅发往本地脚本服务器。原生版本、命令和每份请求/输出均有记录。

## 当前边界与决策

官方说明continue:false能替换工具结果，并特别说明其代码模式行为；本次实际原生请求进一步证明，不能把“钩子执行”和“脚本已输出的结果在下一请求里缩短”混为一谈。[OpenAI Hooks](https://learn.chatgpt.com/docs/hooks)

本地夹具使用fallback模型元数据、独立配置和danger-full-access，而旧C实验使用真实模型、workspace-write及既有宿主控制。因此这里只检验协议能力，不宣称同条件模型或性能对照。钩子原始payload写入后fsync并逐字重读成功；尚未通过模型工具调用恢复，也不是完整持久恢复资格。

新增去噪臂不通过派发门槛，暂不花额度跑三次。不能关闭代码模式、丢掉失败状态，或切换DSH宿主后，将旧C当成仅去噪开关不同的严格对照。普通工具模式虽能替换，也不满足当前全部准入条件。

下一步采用已有DSH真正的结果替换边界做无模型安全/恢复资格，验证原始内容、成功/失败状态和源码旁路；保留原生B/C历史结果。若最终需要更换宿主或工具接入口，必须以新的系统级配置登记，明确多变量限制，不能声称单独证明去噪收益。没有合格接入口时，实际Token收益保持unknown。

程序：validation/probe_native_post_tool_hook.py、validation/summarize_native_post_tool_hook.py。

机器断言：D:/agent-task-runs/wsc-runtime-denoise-admission-20261029-v1/native-hook-qualification.json。

原始证据：D:/agent-task-runs/wsc-runtime-hook-contract-20261029-v1至v10，每份包含registration、请求、stdout/stderr、result；v8至v10包含实际hook输入。

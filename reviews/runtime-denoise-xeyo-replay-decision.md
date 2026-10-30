# 真实回执上的 XEYO 终端去噪：当前样本无付费新增组准入依据

2026-10-29。复用旧三组完整Indexed C的真实回执，不重跑旧B/C，不调用LLM，不修改现有终端显示逻辑或默认设置。

## 实际接入链路

XEYO的BashTool.call在子进程返回后调用output_view.prepare，并把view.text赋给BashOutput.stdout；异步execute经map_tool_result_to_content返回ToolResult.content。退出码、中止、超时和错误状态分别维护。因此它确有模型可见正文之前的处理入口，不是仅修改展示日志。

这里的类型是shell_terminal，表示终端传输而不是“内容无用的日志”。该路径不做JSON骨架、diff摘要、重复读取折叠或正文头尾语义摘要。不能将其与DSH七条有损规则混为同一个已启用功能。当前原生Codex对照不执行XEYO的BashTool，换到这个入口会改变宿主/工具条件。

## 数据与结果

从三份rollout按已验证结构抽出21个shell结果（含4个非零退出结果），绑定原rollout、块和正文SHA。已支持的Promise.allSettled呈现包装照旧复用，不递归解析WSC来源正文。其他文本块不冒充shell回执。

|项目|实测|
|---|---:|
|真实回执|21|
|触发处理|18，全部仅CRLF归一化|
|原始正文|20599字节|
|仅处理后的正文|20248字节，减少351（1.70%）|
|加上原文恢复标记后的完整视图|23002字节，增加2403（11.67%）|
|恢复标记合计开销|2754字节|
|新增原文持久化|20599字节|
|实际模型Token差|未知，未测量|
|真实任务结果差|未测量，没有运行新增组|

18份已落盘原文均按完整字节及SHA重读核对；其余3份未改输出，不将“原样内联”冒充“已从磁盘恢复”。所有处理正文精确等于CRLF→LF，未分类类型原样返回。没有用关键字命中给任务语义打分。预览截断被显式隔离，不把截断算作去噪。

v1已保留；v2仅修正回执语义：未落盘的3份raw_file_roundtrip_verified由误填true改为null，同时记录original_kept_inline。正文大小及命中结果相同，不能把重复审计当作独立样本。

## 耗时边界

v2单次本地回放中，21份纯规则处理合计0.225毫秒；prepare（含其内部规则、原文保存、同步及清理调度）合计61.763毫秒；一次模块导入115.775毫秒。prepare的时间包含规则，不能与规则耗时相加；导入单列。文件重读是验收步骤，不在prepare计时中。

这些是当前机器上一次离线回放的观测，不是延迟分布或原生/WSC墙钟速度对照。调度、缓存、磁盘状态未控制，不能据此声称消除了宿主噪声或证明真实压缩更快。已知解码后的可见回执作为wire占位输入，并无原始传输字节，不能宣称恢复了未知wire数据。

## 决策

当前T1样本不支持为这项终端去噪新开三次付费实验：没有丰富控制序列噪声，唯一正文缩减被恢复标记开销覆盖。字节只用于这项准入盘点，不作为矩阵收益结论，也不换算成假定Token。未安装新的分词依赖，实际模型Token仍为unknown。

这不证明所有大型应用任务的去噪都无收益，也不证明任务质量下降；仅说明当前已有样本和接入口不支持有价值且可归因的新增对照。原生代码模式结果替换、跨宿主可比性及模型实际恢复仍未过门槛。保留用户要求的新增项为未准入，不默认开启，也不重跑旧组来美化结果。

下一步回到WSC主链成本：先盘点真实回查结果中引擎已校验的重复元数据占用，判断是否有不改变正文、状态和来源语义的输入削减空间；有实质收益依据才另立旁路候选。停止围绕这条低命中去噪接入口追加补丁或付费运行。长期目标未完成，原生优越性未得到新增证明。

## 复现与证据

程序：validation/export_recorded_shell_receipts.mjs、validation/replay_xeyo_terminal_view.py。

输入：D:/agent-task-runs/wsc-runtime-denoise-admission-20261029-v1/recorded-shell-receipts.json，SHA c48e295cf5f455a5e33f55516798587280b0ade80af1d21aab7732441ff8d1ca。

结果：D:/agent-task-runs/wsc-xeyo-terminal-replay-20261029-v2/results.json，包含每块操作、状态、前后字节、存储和分项计时，并绑定4份当前源码SHA。原始v1结果及所有恢复文件保留。

```powershell
py -3.11 -B -X utf8 wsc/validation/replay_xeyo_terminal_view.py --inputs D:/agent-task-runs/wsc-runtime-denoise-admission-20261029-v1/recorded-shell-receipts.json --output D:/agent-task-runs/wsc-xeyo-terminal-replay-20261029-v3
```

输出目录独占创建，避免覆盖旧数据；执行时核对来源哈希未变化。

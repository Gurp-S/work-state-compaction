# 六轮协调器与原生压缩证据入口

2026-10-30。0新模型调用。尚未完成真实Bprime/C成对执行。

## 已实现

独立chain_coordinator模块在同一逻辑任务臂内按1..6释放当前轮事件并执行压缩，只在2/4/6执行代码任务续接与验收。适配器只收到初始历史、当轮公开事件和当次任务请求，拿不到oracle或未来schedule；oracle只交协调器的验收回调。

每一压缩或任务阶段先通过DispatchBudget持久预留并绑定输入，再调用适配器；初始化在第一预留区间内，调用前使用remaining取得当前剩余时限。记录的模型回执立即深拷贝；阶段结束汇总已知回执，重复/冲突标记不完整，缺记录不能变成免费成功。模型阶段失败、不完整用量、未确认压缩均停止，无模型自动重试。失败前已有检查点、阶段记录和已知花费保留。

正常关闭在最终或失败阶段的预留内；进程清理可重试，不重试模型。如果预留/结算本身失败使清理只能发生在预留外，则显式cleanup_outside_reservation=true，保留完整链计时，不宣称其时间已全部计入阶段预算。该路径不能视为成功的完整评测。

正式执行需要明确的session_semantics、数据/oracle与账本摘要绑定、完整九阶段上限、显式付费授权以及适配器资格。qualification_only脚本校准结果标记experimental_result=false，不能冒充原生或WSC结果。该协调器不是根预算授权器；正式调用方仍须使用已验证的available根额度并登记根claim、模型、权限、源码及适配器资格。新真实适配器工厂仍待完成，不因存在协议接口就宣称已全部接通。

## 新发现的会话限制

现有MappedCheckpointHost在install中明确检查原生日志不能已有token_usage_record，并要求bootstrap-only新接收聊天，错误为checkpoint_receiver_not_fresh。不能简单把现有实例推进六轮后反复安装检查点，也不能通过覆盖日志绕过这一边界。

已询问用户：“同一会话六轮”是同一逻辑任务（WSC/工作区/历史与费用连续，C边界可换原生聊天），还是严格同一个原生聊天。用户答复前不执行依赖该选择的真实六轮实验。

逻辑任务方案将属于明确登记的系统对照，必须计入C创建接收聊天、上下文搬运和缓存变化，不能称作纯压缩算法差异；严格原生聊天方案还需要可靠的宿主上下文替换能力，目前未证明可行。不把rotate包装成“原线程无损压缩”。

## 原生压缩入口

native_chain_compaction独立模块调用已有session.execute_stage(compact=True)，保留前日志、后日志和事件；使用现有blackbox.compression_evidence核对实际完成、对应回执及opaque项，仅查看结构而不读取/解密摘要。证据读入有32MiB默认上限，失败明确拒绝，不静默截断。每次目录独占创建，不能覆盖旧记录。

复用先前已完成的真实原生V2证据，通过新入口做只读材料回放：confirmed=true，opaque项1，summary_content_inspected=false。回放适配器仅复制旧记录，没有启动原生或调用模型。旧18587 Token不再次计作新费用；此回放只验证新入口能正确读取原证据，不是新的压缩实验，也未验证新协调器内的真实原生进程生命周期。

## 验证与局限

5项协调器检查通过：六压缩/三检查点顺序、未登记付费/不支持原线程连续时开跑前拒绝、第三轮失败保留第二轮结果且不重试、缺回执拒绝免费成功、private oracle改动被摘要绑定拒绝。

首次脚本校准使用空回执宣称完整，被原有application_budget_empty_complete_usage拒绝。没有放宽预算器；改用明确标注synthetic的脚本回执测试调度，qualification_only=true，不参与真实成本汇总。它也说明当前协调器不能把零模型WSC复用边界伪装成一次完整原生阶段；未来如需支持，要有独立、可证明无模型派发的IO计账契约，不能用空数组推定。

命令：`py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_matrix_chain_coordinator.py -v`。

证据：D:/agent-task-runs/wsc-chain-coordinator-20261030-v1，包含scripted-qualification.json、native-replay.json及旧原生证据回放副本。脚本ledger中的usage是虚拟测试值，不是提供方用量；根campaign没有新claim，额度未变化。

下一步在用户选定会话语义后实现真实适配器：C完整原文入库、正常模型选材、验证发布与接收方对账；Bprime同轮触发真实原生V2；两臂第2/4/6任务回执和闭合代码副本交同一验收器。真实付费前仍需根预算可行性核对，52响应不足全部两任务三重复；保持原难度、旧失败和未知用量。

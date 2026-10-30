# 原生阶段计时接线与查询配置生命周期

2026-10-30。默认行为不变，0模型调用，没有重跑真实原生压缩或字段恢复实验。

## 入口接线

新增独立 experiments/native_measured_chain.py，通过 open_measured_session 包装现有会话工厂，记录 host.session_open；调用原 execute_stage 时区分 native.compaction / native.task_stage；同一原生恢复回调经过 MeasuredHandler 记录 wsc.recovery_callback；close记录host.session_close。提供方通过 measured_provider 接原Gate回调，记录provider.http，请求bytes和返回对象原样交接，认证仍由原宿主回调持有。

包装后的会话读取、写入、删除状态字段均转发至原会话，防止 fork_binding 等属性只落在包装对象而原执行器看不到。server、opened等仍为原对象。包装不是原类的同一实例，不对依赖精确类型检查的未知宿主承诺兼容；仅在显式启用的新协调器使用，不改变原生二进制或旧运行器。

外层 full_chain 必须由协调器在初始化之前进入，覆盖来源准备、外置、选材和清理；只包装execute_stage不构成完整链计时。回查是原生任务阶段的子段，不能再与任务阶段相加。提供方可能在另一线程，父子栈不是跨线程因果追踪，不能把线程局部exclusive时长直接算成引擎计算时间；HTTP仍包含网络、远端计算和缓冲。现有PhaseTiming区间并集与原始时间戳保留，无按比例“去噪”。

## 配置跨快照修复

此前ContextReceiver.advance重新调用query_tool(snapshot)，会把显式启用的 infer_json_pointer_units 恢复成False。结构性根因是接收器推进丢失会话级接口配置；现在advance保留该配置，open_context_receiver显式接受开关，工具注册声明与后续查询器保持一致。默认仍False，不补猜字节/字符坐标，也不纠正显式错误单位。

新增回归验证启用后的声明、快照推进后的配置一致、此前查询次数不归零；原有跨工作区、回调重放、权限和容量门槛检查继续通过。此处只解决新开关的宿主接线，不宣称其他自定义查询配置都能自动继承。

候选声明完整UTF8 JSON由925增加到1030字节，增加105字节；这是每次携带工具声明的潜在输入代价。是否抵消缺字段后的重试成本，仍需实际调用频率与完整链Token记录，不能只展示程序查询从2次降到1次就声称总体更省。默认关闭，因此旧组无此声明成本。

## 验证

4项计时入口检查：参数/回执及活状态保持、提供方bytes/返回对象身份、工厂失败不重试、实际MappedContextSession.execute_stage执行与缺失回执仍判未知。最后一项调用真实Python阶段实现，使用脚本RPC并保留产物，未启动原生二进制或调用模型。不能称为新的原生端到端验证。

ContextReceiver 7项检查通过。命令：

`py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_native_measured_chain.py -v`

`py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_native_context_recovery.py -v`

证据记录 D:/agent-task-runs/wsc-measured-native-entry-20261030-v1/checks.json，含源码SHA、验证边界和声明体积。测试临时产物按测试框架正常清理，未把它们冒称留存的真实模型轨迹。

## 当前剩余缺口

当前规范task_specs.build_task仍生成一次旧r1/新r2注册表历史，Cell/TaskCell是单压缩任务入口。它们不是已完成的六轮任务执行器；把同一已完成任务重复六次不能自动证明状态更新/旧状态反转的长期稳定性。

下一步需先补齐六轮事件清单及对应第2/4/6轮程序化任务验收，保留T1/T3实际代码修改和历史依赖；再把本模块、完整链最外层计时、严格available预算读取和原生/WSC两种压缩入口放进同一个协调器。现有封存历史、starter和原任务验收尽量复用，原完成代码/私有oracle不能进入模型环境。此前真实原生压缩资格与回查资格已完成，不重复付费做准入。

当前可用10920468 Token / 52响应 / 2004秒；完整三重复仍无足够响应保证。新协调器必须在派发前明确阶段及总预算，单组不能视为三重复，不为省预算用简单问答代替代码任务。主目标——长期任务质量与相同预算下的收益——仍未验证完成。

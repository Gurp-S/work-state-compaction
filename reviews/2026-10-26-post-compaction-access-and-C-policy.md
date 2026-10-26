# 跨压缩工具访问通过；C专用自动压缩旁路已接入

2026-10-26。本轮补上上轮明确缺失的真实工具访问证据，随后实施受证据绑定的实验入口；没有启动A3业务开发或正式B/C。

## 真实能力证据

`D:/agent-task-runs/native-post-compaction-access-20261026-v1`，单次登记两个原生turn，共用同一服务、thread与原StudyBudget。本臂总上限200000 tokens/8响应/180秒，不在第二步重置；无自动重试。

源记录顺序为：启动PowerShell进程 → 外层exec yield及对应wait结果 → 同turn原生自动压缩及匹配回执 → 第一turn正常完成 → 第二条独立请求 → tools.write_stdin(session_id=1078) → 实际返回同PID24900、同nonce、counter心跳 → 第二turn正常完成。

第二条请求没有exec_command或新进程替代。外层三次调用（startup exec、wait、post exec）均与真实结果配对，两个阶段account_turn均完整，同一个pid在压缩后访问前后均为Job实时成员。独立审核最初误设“总共恰好两次外层调用”，遇到实际yield/wait而失败；按真实调用语义修正审核，未重跑模型。

本次6响应/156789 tokens，其中压缩49039；52.844秒，未超本臂上限，源文件hash不变、自有进程清理为空。当前最新准入记录再扣零模型配置读取1秒，为87334849 tokens/1734响应/19185秒，非现金余额或旧未知费用上界，旧未知账本不改。

可证明的范围：一个持久PowerShell native命令会话可跨原生自动压缩继续访问。不是全部工具/浏览器/后台工作负载证明，不是业务正确续接或WSC语义/经济收益。协议fixture阈值32000不能升级为应用96000资格通过。

## 实验旁路

新增experiments/native_c_auto_compaction.py；仅注册native_c_auto_compaction并明确study_arm=C才生成启动参数model_auto_compact_token_limit=96000。资格文件hash、其原始来源hash和CLI/model/effort/features必须匹配，实际跨压缩访问及完整本地用量证据缺失则拒绝。没有新增模型可见劝导文字，不改compact_prompt或上下文窗口。

native_host_controls.settings只有字段显式存在时才调用该模块；无字段返回值保持原样。ApplicationStudyWorker另以真实job arm拒绝在B作业携带此开关。选择性实验入口已接入，不等于把尚无业务收益的新机制并入产品主链路。

4项新准入检查通过：默认/B未启用参数完全相同、C追加唯一阈值；B和未知臂拒绝；未知用量/未证实工具访问拒绝；native身份及原资格来源变化拒绝。原3项host controls检查通过。只验证本改动范围，没有全项目回归。

实际零模型接线验证 `D:/agent-task-runs/wsc-c-auto-compaction-policy-20261026-v1`：通过上述真实旁路启动服务，config/read读回96000且origin=sessionFlags。无turn/start、没有配置文件写入，清理为空。没有把这次读回升级成96000下业务压缩已验收。

## 下一次业务运行前的具体准备

只读比较原C工作区与1162文件的S2 initial_manifest：6个原文件变化、0缺失、265个新增文件；6个变化文件在冻结S2均找到精确hash匹配的恢复来源。新增约54.6MB，包含旧S3验收截图/结果以及validation下node_modules。它们不能留在新运行环境中形成旧S3材料泄漏，也不能因名称为node_modules而盲目复制、删除或追入链接。

本轮只写入s2-restore-plan.json，没有恢复或移动工作区，没有重新生成选材，没有复制浏览器/大依赖。新运行仍未准入。下一步先将旧S3六文件差量和新增材料按真实文件/链接归属保留，恢复C至精确S2并核对完整manifest；复用实体私有依赖/浏览器、原32765字节校准包和原S3请求，重新绑定本版旁路/验收器/累计预算，才执行一次C资格试验。不能直接重跑旧driver或改用现有S3作为起点。

原生B保持默认，未来需同阈值的原生诊断对照区分“更早压缩”和WSC的增量。协议探针结束，不再追加同类问答；五任务各三轮和长期主目标仍未完成。

# 严格结算与续用图修正

2026-10-30。用户明确批准“允许追加严格结算规则”，原总上限与旧claim不改，未知用量继续冻结。

## 修正此前审计遗漏

此前审计只识别 next-runtime-group.claim.json，遗漏 controls-continuation、paired-r1-allocation、hot-continuation-probe 等不同文件名及多级续用。因此“第三批25响应可作为释放候选”的结论不完整：其中24响应、900000 Token、900秒已有hot诊断预留，且该子账本有未知用量，必须整笔保留。

结构性修复是遍历每个已登记child根目录下的全部 *.claim.json，递归检查所有层级，拒绝环和重复child身份。算术上先扣本节点实际记账及所有直接子预留；未知子节点只能扣完整预留，不能用已知花费替代。没有遍历工作区副本或 frozen-source 账本。7根与5个后续节点均进入新图；audit-v1/v2原结果仍保留，新audit-v3更正。深层旧登记无注册摘要或用量未知，不能因此推定可信或释放。

此前未执行退款，故遗漏没有造成重复分配。3项回归覆盖任意续用文件名、三层图和重复节点；4项算术检查覆盖重复/未知credit、负数/未知/过量释放及旧claim不变。

## 已追加的结算

只针对根节点尚未分配给子实验的剩余部分；不释放子预留，不覆盖原失败。

|根登记|释放Token|释放响应|释放秒数|
|---|---:|---:|---:|
|第三批T1重复2/3|67260|1|112|
|真实原生V2压缩|61413|0|137|
|合计|128673|1|249|

之前10791795 / 51 / 1755，之后 **10920468 / 52 / 2004**。这是可用分配上限，不是账户余额或完整账单。未增加原总上限。

每笔在父目录追加原claim对应的 .claim.settlement.json；原claim、原ledger、旧失败与未知不变。规则文件及完整核验输出在 D:/agent-task-runs/wsc-strict-settlement-20261030-v1。父目录为 wsc-deferred-catalog-qualification-20261027-v1。

核验要求：注册摘要匹配，账本closed且最终事件closed，无未知/在途/未结ticket；每个reserved有且仅有一次settled；阶段完整且有唯一精确匹配的原始phase文件；rollout及压缩前前缀SHA匹配；重新用原生日志执行account_turn得到完整且精确相等的回执；响应ID无重复且总数/Token与账本一致。后续使用 available(parent) 必须再次验证来源摘要、子claim集合与释放额，原始 remaining 不自行计入新credit。旧运行器仍使用原始扣减口径，保持保守；新协调器接入前不能宣称所有入口已支持结算。

第二次恢复的 live-outcome 使用不同的聚合格式，未满足“唯一精确phase”要求，本次拒绝释放，未为了成功而放宽核验。其他含未知记录仍冻结。

原始日志核验及失败闸门5项检查通过，覆盖有效完整回执、关闭但未知、原文变化、总数不符、未结预留。首次测试暴露SQLite连接上下文仅提交但不关闭造成Windows文件占用；已用closing明确关闭，5项重跑通过。没有删除旧证据。两次结算执行得到相同输出，既有追加文件未重写，available独立读回核对一致。

运行：`py -3.11 -B -X utf8 wsc/validation/settle_campaign_reservations.py --parent D:/agent-task-runs/wsc-deferred-catalog-qualification-20261027-v1 --rule D:/agent-task-runs/wsc-strict-settlement-20261030-v1/rule.json --out <新的输出JSON路径>`。已有结算只核对不重复加额。

## 下一步

本轮0模型调用，未启动付费实验。52响应仍小于六轮双任务双臂三重复的乐观下界72，不用简单题代替长程任务。继续将分段计时、严格可用额读取和固定查询契约接入共同宿主的长程协调器，明确一次完整配对所需预算；为剩余全部矩阵工作给出具体缺口，再讨论预算或阶段安排。不得把一个配对当三次重复结论。

# 显式控制来源：失效规则与保留规则统一

本轮是宿主中立核心的代码正确性修复，未新增实验模型调用，未运行或授予 C 资格，也不是 Cursor 或 WSC 总体收益实验。

## 结构性原因与修复边界

旧 `events.ingest` 把 `control=True` 或 user/system/developer 角色视为控制变化；`view_budget.mandatory_sources` 却只按角色保留。合法的无角色控制事件会递增 control_epoch，但空选材后的视图不包含它；生成预算低估必需记录，增量入口也不会再展示它。已有冷档仍保存来源，不能据此说热视图未丢约束。

新独立模块 `src/wsc/control_sources.py` 提供共享机械规则：显式布尔控制标记或既有控制角色。摄入失效与必保留来源共用这条规则，准备视图、最低预算、选材事实和增量生成沿用已有入口，不引入语义评分、自动规划或额外指令。原角色、记录顺序、载荷与观察时间不改写。

仅有 `kind="control"` 而没有控制标记/角色的事件，保持此前契约；普通观察仍可省略。显式控制与 opaque 同时出现时不能生成可读热记录，沿用 `opaque_hot_selection_unavailable` 在调用模型前拒绝；普通 opaque 仍留冷档。本轮不定义新宿主控制消息权限，不把无角色事实提升为 user/developer。

## 修复前后同检查

隔离目录：`D:/agent-task-runs/wsc-control-retention-20261023-v1`。

1. 修改前逐一核对上一交付的 110 个源码哈希，建立 baseline/candidate 副本；原生 Codex 和 XEYO `python/` 没有改动。
2. 同一 `test_control_retention.py` 的 7 项检查在旧版全部失败，原始输出保存在 `baseline.txt`。
3. 先只修改 candidate 的共享规则及两处入口；7 项控制检查、3 项生成可行性、6 项选材事实、5 项增量生成，共 21 项通过，unittest 用时 0.656 秒，见 `candidate.txt`。检查包括生成前拒绝、不新增用量尝试、空选材权限校验、完整导出、精确字节预算、幂等摄入和失效。
4. 三个运行文件才移入当前 `wsc/src`；逐字核对整个运行目录和四个检查文件与已测副本一致，不重复运行相同检查。

这是确定性修复前后对照，不是模型行为或经济性 A/B。具名检查未覆盖所有宿主和所有事件组合。

## 已有视图的兼容性

另用旧代码实际生成带遗漏的数据库，交给新代码：旧视图被 `frontier_previous_control_missing` 拒绝，在导出/调用前停止；从同一不可变来源及相同空 Selection 重新 prepare 后，增量材料包含 s1。来源摘要不变、cursor=0、模型尝试为零，见 `compatibility.json`。旧视图没有被静默重写，重准备不是重新安装或重新证明原语义记录。

原生适配器本来就按 user/system/developer 设置 control；当前实验观察事件显式 control=False。因此本次缺陷的已证实范围是宿主中立显式控制入口，不能用它解释此前原生 C 的短哈希、选材或输出偏多。那些问题的实际证据仍分别在 span-boundary、scope-observation 等报告中。

## 当前交付与下一步

当前 112 个 Python 文件绑定 `validation/control-retention-20261023/delivery.json`，紧凑版本 `versions/20261023-control-retention-v1.zip`。旧110源码版本、失败检查和隔离副本保留。当前代码已变化，之前仅准备的生成目录 pins 已过期，不能直接执行或补写旧资格。

下一步仍是独立真实任务上的当前 C 资格，评估版本变化后的证据适用性与完整成本。旧资格器硬编码 JSONL 的 18 项验收，连续任务驱动硬编码上一个已封存的 revision 题；两者均不能直接拿来给新任务授予资格。应先确定任务与真实阶段验收，复用现有计费/同源准入，不再重复旧哈希报告题、放宽停止上限或继续围绕本次控制规则增加小实验。Goal 保持 active，整体目标尚未达成。

# WSC nosig 基线臂（pmx-wsc-20261121）

1. **触发**：WSC 引擎在达到 `forceRatio`（0.8）时压缩被遮蔽区间，`minReclaimRatio` 0.15 防止小回收；compaction-basic 被禁用。
2. **检查点内容**（passage，按序）：控制原文（本臂上限 0 = 不截断）→ 按 rank 排序的账本句（fact 0 / verification 1 / decision 2 / requirement 3 / constraint 4）→ `## Current state (model account; unverified)` 状态块 → 最近四次机械校验 → 值账本（`V<n>`，可 `fetch #seq` 回读）→ 证据索引（`E<n>`，带 seq）。
3. **跨压缩记忆**：抽取条目、控制原文与值行写入 `$DSH_HOME/wsc/nosig/<session>.jsonl`；值账本按文本去重、全局编号，跨区间持续累积（本次修复的本质项）。
4. **状态投影**：从账本条目与机械证据（编辑/测试/命令）投影 done/open/next/unknown；引擎注入的通知不进入需求，只读探针不转成需求，绝对路径与相对路径按后缀匹配。
5. **本臂不含**：控制原文字节上限（`controlMaxBytes=0`）与 passage 工作集（`passageWorkingset=false`）。这两项由 fix/cap/ws 臂单独定价。

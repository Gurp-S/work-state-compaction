# 增量选材旧 view 完整性修复

2026-10-28。修复独立实验旁路 `experiments/native_incremental_candidate.py`，不修改核心选材算法、原生 Codex B、提示词、表示格式或预算，不启用其他候选。本轮运行有限定的代码回归检查，没有模型调用、性能测量、任务续接或 B/C 实验。旧实验费用、失败和未知项不变。

## 修复前的三个问题

**结构性根因**：frontier 直接 SELECT＋json.loads 旧 view，只核对 binding 的 cut/source digest、理解 ref 与 excerpt key 集合。body 内 clue、来源行或 excerpt 内容改变而 digest 不更新时，既有检查没有统一校验正文封印。

**防止重现的规则**：增量选材消费已存储 view 时复用现有 `snapshots.view_record`，先检查 body digest，再构建旧选择输入；不维护第二份正文校验逻辑，不让模型修补坏绑定。

**回归判据**：原 digest 保持不变、只修改 clue/来源/同 key excerpt 时，在冷归档写入、生成回调和 usage 登记之前拒绝；有效 view 的完整 material/offered 序列化与旧读取方式相同；缺失 view 保持原错误码。

## 前后结果

|检查|修复前|修复后|
|---|---|---|
|clue 改动但摘要不变|错误接受|view_integrity_mismatch|
|选中来源内容改动但摘要不变|错误接受|view_integrity_mismatch|
|excerpt 内容改动、key 不变、摘要不变|错误接受|view_integrity_mismatch|
|坏旧 view 能否进入生成回调|错误进入本地测试回调|生成未调用、usage未登记、归档未创建|
|有效 view 与旧读取方式的完整序列化输入|一致|一致|
|旧 view 不存在|原错误码|仍为 incremental_previous_view_missing|

同一组6项检查，修复前4失败/2通过，修复后6通过。失败来自预期拒绝没有发生，不是环境或额度问题；本地测试回调只作断言，没有任何模型。旧源码及完整前测日志保留。

随后只运行相邻的8个增量选材用例，8项通过，覆盖旧理解修订、旧片段复用、跨会话拒绝、失败用量/禁止重试、来源别名与上一轮选择显式保留/丢弃等原有行为。合计14项定向代码检查通过；没有扩大成全量测试、故障实验或性能跑分。

## 实现与边界

替换原来的自行解析读取，调用已有 `view_record`。只对 `view_unavailable` 映射回原来的 `incremental_previous_view_missing`；完整性失败保留统一中性结果 `view_integrity_mismatch`。原有 cut/source/ref/key 和原文范围校验继续执行，查询次数没有通过额外预读增加。

这是现有显式实验入口的正确性修复；独立 WSC 默认链路没有切换，普通任务恢复端口和真实容量准入仍未接通。历史模型结果没有重跑，不能称当前完整运行质量已重新验收，也没有新的 Token/速度收益。

digest 与 body 同库保存，提供一致性检测，不是恶意数据库写入者无法伪造的签名。若两者一并被改写，不能仅凭该检查宣称真实性。此修复针对已确认的绕过既有校验路径，不扩大安全保证。

凭据目录 `reviews/previous-view-integrity-fix/` 保存 before 源码、before/after/adjacent 日志、机器结果与指纹。不复制研究数据库或冷目录。

复现定向回归：

```powershell
py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_incremental_previous_integrity.py -v
py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_native_incremental_candidate.py -v
```

下一步继续按统一缺口清单处理正常任务的恢复接入和容量边界；不开模型、性能或 B/C 实验，不增加新的压缩表示或恢复模型。

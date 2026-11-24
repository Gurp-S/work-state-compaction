# thin 与全量 WSC 的内容差异

结论：thin 比 WSC 大 0.65–0.77 KB，差异**只来自账本更新语义和 Work state**，其余段落逐字节相同。
数据来自 run `20261118-140946`（三例，deepseek-flash，已含去噪瘦身），可用 `live.py --jobs 3` 复现；
`runs/<run>/<case>/presented-wsc.txt` 与 `presented-wsc-thin.txt` 是两臂实际模型输入。

## 分段字节

| 段落 | lease WSC/thin | checkpoint WSC/thin | handoff WSC/thin | 来源 |
| --- | --- | --- | --- | --- |
| 用户要求（Control） | 316 / 316 | 171 / 171 | 301 / 301 | 两臂同一个 `passage.render` |
| Checks | 343 / 343 | 349 / 349 | 270 / 270 | 两臂同一个 `receipts_from_events` |
| 证据索引 | 907 / 864 | 874 / 874 | 829 / 829 | 两臂同一个 `index_from_events`；thin 过滤失效版本行 |
| 账本 | 330 / 389 | 241 / 655 | 224 / 811 | 差异一 |
| State | 0 / 261 | 0 / 243 | 0 / 317 | 差异二 |
| 合计 | 1902 / 2181 | 1641 / 2300 | 1630 / 2536 | |

固定格式的去噪（模板头、索引标签 100→72、terms 去重与上限 2、状态缺口归并、Control 精确去重）
在每个检查点上省约 55–190B；模型输出内容逐 run 变化，所以总量只能参考：
thin 在相同三例上由 2686 / 2464 / 2690 降到 2181 / 2300 / 2536，
WSC 由 1918 / 1720 / 2036 降到 1902 / 1641 / 1630（含重写内容差异）。Discover/Retrieve 保持 1.00。

## 占比

| 段落 | lease thin | checkpoint thin | handoff thin | lease WSC | checkpoint WSC | handoff WSC |
| --- | --- | --- | --- | --- | --- | --- |
| Control | 14.5% | 7.4% | 11.9% | 16.6% | 10.4% | 18.5% |
| 账本 | 17.8% | 28.5% | 32.0% | 17.4% | 14.7% | 13.7% |
| State | 12.0% | 10.6% | 12.5% | 0 | 0 | 0 |
| Checks | 15.7% | 15.2% | 10.6% | 18.0% | 21.3% | 16.6% |
| 索引 | 39.6% | 38.0% | 32.7% | 47.7% | 53.3% | 50.9% |

两臂都是索引占比最大；差异在 thin 把约 15–19% 给了 Work state，账本占比也因此上升。

## State 的呈现

渲染规则见 [passage.py:23](../src/wsc/passage.py#L23)：按 done → open → next → unknown 顺序拼成一句：

```
State: done: <条目；条目>. open: <条目>. next: <条目>. unknown: <条目；条目；…>.
```

内容来源（[live.py:1052](../benchmarks/coding_compaction_v1/live.py#L1052)）：

- 模型填 done/open/next/unknown 四个槽位，每槽最多 6 条、每条截到 160 字符。
- 引擎追加机械缺口：有 open 无 next、某文件编辑后无验证、检查之后又被编辑、验证没有版本绑定；
  同类 `no verification evidence for …` 会归并成一行。
- 失效条目的整句与 `<Vn> checked` 短语在渲染时被过滤，旧验证不能经状态回流。
- 预算裁剪先删索引再删低价值账本，**状态不被裁剪**。

本轮 lease 的实际状态（261B，末轮模型没有填 done）：

```
unknown: no post-edit verification for src/wsc/resource_io.py via python -m unittest tests.test_resource_io
unknown: no recorded next action to resolve PermissionError [WinError 5] in tests.test_resource_io
unknown: src/wsc/resource_io.py changed after the check at #25
```

三例的槽位计数：lease 0/0/0/3、checkpoint 1/0/0/3、handoff 1/0/0/3（done/open/next/unknown）。
**open 与 next 全部为空**：当前用例没有“未完成且下一步未被复述”的工作，状态实际上只在记录已完成的检查与缺口。
这正是新测试方案要补的场景（见 [eval-redesign-v1.md](eval-redesign-v1.md)）。

## 账本的呈现

渲染规则见 [passage.py:14](../src/wsc/passage.py#L14)：只取 active 条目，按
constraint > requirement > decision > verification > fact 排序，同文本只出现一次，失效条目的整句与版本短语被过滤，然后写成：

```
Ledger (current): Decision: <text>. Context: <text>. Verification: <text>.
```

- 文本来自模型 JSON 槽位，单条上限 220 字符；缺标识符时引擎追加 `Exact source tokens: …`（≤120B）。
- WSC 的账本来自数据库当前投影（整篇重写后的结果）；thin 来自增量修订后的活跃条目。

本轮 lease 的实际账本（389B，4 条）：

| 类型 | 字节 | 内容摘要 |
| --- | --- | --- |
| decision | 102 | identity lease 而非文件锁，Windows 无法设置 share mode |
| fact | 86 | 失败路径与调用方 |
| fact | 82 | `PermissionError [WinError 5]` 发生在 `.pending-*` 重命名 |
| fact | 57 | `max_open_handles=4096` 当前导出句柄预算 |

三例活跃条目数 4/6/6；WSC 最终账本约 2–3 条（第 1 轮曾写 8/8/7 条，第二轮重写后合并）。
本轮 lease 的检查结果由 Checks 段承载，thin 账本没有重复写入验证条目。


## 差异一：账本是“整篇重写”还是“增量修订”

- WSC：第二轮由 distill 模型重写整个账本，`present` 再从数据库投影当前条目
  （[live.py:630](../benchmarks/coding_compaction_v1/live.py#L630)、[live.py:696](../benchmarks/coding_compaction_v1/live.py#L696)）。
  本轮 lease 第 1 轮写入 8 条，第二轮重写后最终视图只剩 3 条；字节少，但保留什么取决于当轮模型。
- thin：第二轮是增量修订（`entries` / `replaces` 作用于现有账本，[live.py:1106](../benchmarks/coding_compaction_v1/live.py#L1106)），
  不整篇重写，因此早期的决策（identity lease 而非文件锁）不会因为一次重写被合并掉。
  本轮活跃条目 4 / 6 / 6，账本字节 548 / 603 / 761。
- 标识符回填条款（每处 ≤120B）计入账本：本轮 lease 1 处、handoff 2 处、checkpoint 0 处。

## 差异二：Work state

thin 独有 done / open / next / unknown，并附引擎机械缺口（缺少的编辑后验证、失效检查）。
WSC 视图没有这一段。它不是摘要，而是“压缩后如何继续”的确定状态；删掉它就退回 WSC 的语义。

## 这些字节买到了什么

| 多出的内容 | 保证 | 删掉的后果 |
| --- | --- | --- |
| Work state | 下一步与未知项显式存在，不依赖模型重推导 | 压缩后需要模型重新判断该做什么 |
| 增量账本 | 早期结论不因某轮重写丢失 | 账本内容取决于当轮 distill 输出，存在漂移 |
| 标识符回填 | 源里的路径、错误码、测试名逐字保留 | 退回模型改写，标识符可能被 paraphrase |

质量上没有用字节换损失：同一 run 中 thin 与 WSC 的 probe、recall、约束保留一致（native 更低），
thin 仍比 native 小 35–45%。因此：

- 只比字节：WSC 胜。
- 要“压缩后可确定地继续”：thin 多出的部分是保证本身，不能再删。

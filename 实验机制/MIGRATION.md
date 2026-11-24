# 迁移说明：主路径已移除的接口

这些接口随机制一并移出 `src/wsc`。此处只记录调用方需要知道的契约变化；
恢复办法见 README。

## 选择与事实

| 已移除 | 替代 |
| --- | --- |
| `WSC.prepare(..., include_selection_facts=True)` 及 `body["selection_facts"]` | 无。模型视图只保留 passage（控制、账本、状态、回执、索引），不附带事实报告 |
| `wsc.selection_facts` / `projected_selection_facts` / `span_selection_facts` | `wsc_experimental.*`，需自行接线 |
| `view_budget.admit_generation` 对事实开销的扣减 | 预算只按 passage 字节裁剪（先索引后低价值条目） |

## 宿主验证回执

| 已移除 | 替代 |
| --- | --- |
| `wsc.verification_state` / `verification_capture` / `verification_checkpoint` | thin 层由引擎从事件机械推导回执（编辑→检查→失效），见 `benchmarks/coding_compaction_v1/live.py` 的 `receipts_from_events` |
| `publication` 中的验证作用域与尾部回执检查 | 无。回执只进入 passage，不进入发布契约 |
| `ContextCheckpointAdapter` 解析视图 JSON 的 `historical_excerpts` | 适配器只做运行期投影与尾部投递替换；首条 item 是自然语言 passage |

## 状态写回

| 已移除 | 替代 |
| --- | --- |
| `core.write_back(...)` / `ContextRuntime.write_back(...)` | 账本由 `Understanding` 写入；H3 状态差集降为内部审计：`prepare(audit_state_delta=True)` 写入 `body["state_delta_audit"]`，默认不生成 |
| `state_writeback` 模块 | `wsc_experimental.state_writeback` |

## 查询与发布策略

| 已移除 | 替代 |
| --- | --- |
| `WSC(query_policy=...)`、`prefix_index_v1`、`bounded_catalog_v1` | 无。发现靠 passage 中的机械索引（每类保留一个槽位，重复爆发去重） |
| `WSC(publication_policy=...)` | 无。发布契约固定为最小集合 |
| `events` / `snapshots` / `settlement` / `continuation_inspection` 的 `indexed` 分支 | 无 |
| `wsc.scoped_queries` / `publication_memory` / `quote_selection` / `span_selection` / `span_boundaries` | `wsc_experimental.*` |

## 生成器

| 已移除 | 替代 |
| --- | --- |
| `bounded_generation` / `generation_frontier` | `wsc_experimental.*` |
| `generation_api` 的 `KINDS` 只剩 `json-command` | 无 |
| CLI `--prefix-index`、`--bounded-catalog`、`--bounded-command`、max-output 系列 | 无 |

## 归档与回收

| 已移除 | 替代 |
| --- | --- |
| `durable_ops.recover()` 的 blob 回收及其 `blobs` 字段 | 无。未提交对象留在磁盘，由外部流程处理 |
| `content_archive` 发布对象 | `wsc_experimental.content_archive` |
| `blob_gc` | `wsc_experimental.blob_gc` |

## 受影响的隔离测试

`run_tests.py` 跳过 19 个依赖上述接线的模块，并在输出中列出原因；
`python 实验机制/run_tests.py --all` 会在恢复接线后尝试全部。

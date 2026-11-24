# 实验机制

这里存放从 WSC 主路径移出的机制。它们不再被 `src/wsc` 导入，也不参与默认测试与真实模型评测。

- 选择事实：selection_facts / projected_selection_facts / span_selection_facts
- 宿主验证回执：verification_state / verification_capture / verification_checkpoint
- 状态写回：state_writeback
- 冗余选择词汇：quote_selection / span_selection / span_boundaries
- 生成器：generation_frontier / bounded_generation
- 查询/发布策略：scoped_queries / publication_memory / blob_gc / content_archive
- 对应测试在 tests/，通过 conftest.py 加入路径

运行可执行子集：`python 实验机制/run_tests.py`（跳过依赖已移除接线的模块并列出原因）；
恢复接线后用 `--all` 跑全部。调用方需要迁移的接口见 [MIGRATION.md](MIGRATION.md)。

恢复方式：把需要的模块移回 `src/wsc`，恢复 `core.py` / `publication.py` / `events.py` / `durable_ops.py` / `context_runtime.py` / `generation*.py` / `cli.py` 中的接线。

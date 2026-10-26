# 生成目录与历史执行目录的身份修复

上一轮增量生成出现“当前工作目录是另一副本”的无依据判断。本轮找到独立于模型文字的具体输入问题：`run_frontier_generation.py` 把空的生成器cwd也写进了WSC Store的workspace绑定；请求没有另外提供来源执行目录，后续执行目录也未注册。这三种身份被实验入口合并了。

来源的原生turn_context记录了真实执行目录 `D:/agent-task-runs/wsc-generated-covered-C-20261023-v1/workspace`，可直接按线程、回合与归档哈希绑定，不需要从自然语言猜测。

已用独立 `native_generation_scope.py` 提取生产者记录的历史执行身份。WSC来源状态绑定历史任务目录；原生生成进程仍在独立空只读目录运行。生成请求分别给出 generator_workspace、historical source_execution 和未注册的 continuation_execution。后者保持workspace=null，不自动宣布存在另一副本或授权下一次任务执行。没有改原生模型提示、配置、理解字段或发布契约。

本轮先检查当前86个Python文件仍匹配上轮回执，之后只验证改动影响的范围：6项身份与入口检查通过，0.003秒。另对已有真实54来源做完整离线准备，两个数据库及实际请求都验证为“历史任务目录 != 生成目录”，未来执行身份仍未知。目录 `D:/agent-task-runs/wsc-frontier-generation-scope-20261023-v1` **仅离线准备，没有started.json，没有新模型调用**。它不是对上一轮失效实验的重跑，也没有新的有效比较结论。

当前回执：`validation/generation-scope-20261023/checks.json`、`actual-source-replay.json`。这是小范围的生产者身份修复，尚未验证模型读到新事实后一定不再误判；不能宣称语义问题治愈。

完整哈希被模型写短的问题仍未修复。已有精确原文同时出现在生成输入与导出呈现中，不能归因为冷档丢失；不使用正则自动改写模型结论，也不靠重复生成挑选正确结果。下一步针对既有生成产物中的“解释与原证据相冲突”建立真实下游判断，而不是先追加更多状态字段。上一失效实验的费用、两个缺陷与启动不一致记录继续保留。

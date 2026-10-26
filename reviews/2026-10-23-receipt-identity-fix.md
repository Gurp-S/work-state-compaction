# 回执身份旁路修复与离线对照

## 根因、规则与验证

根因：两个实验生产入口在`receipt_path`旁发布`receipt_sha256=digest(receipt)`，却未说明该哈希来自JSON值的规范化序列化，而非该路径的文件原字节。真实B交接按文件字节核对时得到不同值；这是真实表达歧义，不是归档损坏。

结构规则：每个哈希声明计算域。新增独立模块`experiments/native_receipt_identity.py`，仅在`bind_receipt_file=True`时启用。保留旧`receipt_sha256`的JSON值含义，增加`receipt_sha256_basis=canonical_json_utf8_v1`、文件原字节哈希及其`raw_file_bytes`计算域。JSON规范为排序键、紧凑分隔、ensure_ascii=False、allow_nan=False、UTF-8，定义在模块文档中。两种哈希从同一次文件读取校验关联，拒绝回执值不符、重复键、损坏编码及非有限数。

回归：同内容不同缩进/Unicode转义/BOM应保持值哈希而改变文件哈希；passed或数字类型变化不能继承旧回执；旧默认入口仍返回原字段；新增入口在回执不符时先于创建检查点拒绝。首次和后续宿主检查点都实际构建包并检查模型可见观察。

## 实际结果

- 新检查8/8通过，覆盖上述身份与两条发布路由；RPC导入使用测试替身，未运行新模型。
- 受影响的现有消息检查点、宿主、后续检查点、续接流程检查38/38通过。不是全项目测试。
- 对原B的8项、11项回执做同文件旧/新对照：两份旧值哈希保持，新值哈希与文件哈希分别核对通过，原文件未改。
- 代码清单135个Python文件，绑定在[检查回执](../validation/receipt-identity-20261023/checks.json)。旧/新对照分别为[before](../validation/receipt-identity-20261023/before.json)、[after](../validation/receipt-identity-20261023/after.json)。

只有实验旁路入口接受该开关：`prior_fact`、`checkpoint_sources`、`prepare_message_checkpoint`、`PendingHostCheckpoint`和`PendingSuccessorCheckpoint`。默认仍兼容旧合同；现有登记脚本没有被自动切到新模式。新研究需在登记中明确启用并对两臂一致应用。核心`wsc/src`和主工程`python/`未由本修复修改。

这是一次文件观察的身份，不是路径永久不变、跨文件原子性或语义正确性证明。尚无新模型实验验证它是否减少补证、输出或费用。原严格JSONL两臂产物、登记验收和资格更正均保留，不把修复后的当前源码冒称原实验运行源码。

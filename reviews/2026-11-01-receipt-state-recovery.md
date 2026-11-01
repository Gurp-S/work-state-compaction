# WSC 回执状态恢复与来源查询定点修复

基线：`ad25f0a`（索引主键身份、链路空洞与计数语义）。本次只改回执链的状态恢复、
计数一致性、持久化类型校验与来源查询，不重构 WSC 其他部分。

## 结构性根因

1. **状态行是"历史长度"的唯一记忆**。`wsc_receipt_state_v1` 丢失后，`advance_receipts()`
   从 `(0, GENESIS)` 起扫，把已存在的链记录当作"本次扫描到的新回执"，`scanned` 被当成
   增量加进 `receipt_count`。链本身完好，但计数器变成了"每次恢复就翻倍"。
2. **计数只有 `advance_receipts()` 一个写者**。它无法判断自己是否在重走历史，也没有
   第二处能在证据充分时纠正它；`verify_receipts(full=True)` 已经算出了权威的链长，
   却不修数。
3. **持久化值被 `int()` 归一化**。`int("1")`、`int(1.5)` 都会得到合法位置/计数，于是
   SQLite 里的 TEXT/REAL 损坏状态被读成合法检查点。
4. **来源查询把候选集物化**。`SELECT receipt_id ... WHERE source_id=?` 后 `.fetchall()`
   再逐条 `SELECT data`，代价随"提及该来源的回执数"线性增长，且是 N+1 次往返。

## 修复

- `_restore_receipt_state()`：状态行缺失时不再假定空历史。按 rowid 顺序逐条校验
  已存在的链行（位置、receipt_id、source_ids、link 全部对得上权威回执），校验通过
  才恢复游标；链与回执对不上、或链行越过最后一条回执（无法证明的前缀）一律
  `receipt_state_unrecoverable`，不做猜测性重写。
- `advance_receipts()`：`scanned`（本次走过的行）、`inserted`（真正新增的链行）、
  已存在且校验通过的行三者分开；只有 `inserted` 增加 `receipt_count`，恢复性重扫
  不再重复计数。返回值新增 `inserted` 与 `count`。
- `verify_receipts(full=True)`：一次通过的全量审计是唯一能"断言历史规模"的作用域，
  此时把 `receipt_count` 修成实测链长（覆盖 `-1`、`0`、错误正数）；审计失败则不动。
  增量审计不修数。
- `_stored_int()` / `_stored_head()`：只接受 SQLite 实际存为 INTEGER 的值与 64 位小写
  十六进制头；REAL、TEXT、NULL、负数、坏头一律 `receipt_state_invalid` /
  `receipt_count_invalid`，不再被 `int()` 悄悄转成合法检查点。
- `audit_cache._reusable()` / `_chain_state()`：检查点里的计数、版本必须是真 INTEGER，
  rowid 与 link 也必须类型正确，否则不复用（重算而不是信它）。
- 来源索引新增覆盖标记 `wsc_receipt_aux_v1.indexed_through`（`AUX_VERSION=2`，旧库就地
  迁移）：`advance_receipts`、`rebuild_receipt_index`、迁移重建都会同步写它。
- `is_delivered()`：命中路径一次 JOIN、惰性读取（首个确认即返回），语句数不再随候选
  数增长；未命中时才检查"索引是否覆盖整条链"，不覆盖则先重建索引再回答，避免把
  索引滞后误报成"从未呈现"。索引行被单独删除属于行级损坏，由
  `rebuild_receipt_index()` 的 `receipt_index_mismatch` 检出，不在读路径处理。

## 测试（`tests/test_receipt_state_recovery.py`，23 项）

| 组 | 覆盖 |
| --- | --- |
| 状态恢复 | 状态行丢失后重建且计数只算一次、重建后新回执仍可链接、回执被篡改拒绝恢复、链空洞拒绝恢复、恢复中途失败整体回滚 |
| 计数一致性 | 全量审计修正错误正数与 `-1`、增量审计不改数、审计失败不改数 |
| 存储类型 | INTEGER 正常读取；REAL/TEXT/NULL 计数、负数/REAL 位置、坏头全部拒绝；检查点里 REAL 计数不复用 |
| 来源查询 | 命中/未命中、伪造索引行不算投递、索引表被删自动重建、覆盖滞后在未命中时先重建、命中语句数与候选数无关 |

```
py -3.11 -m unittest discover -s tests -p 'test_receipt*.py'   # 54 passed
```

## 前后对照（`benchmarks/receipt_index_ab.py`）

同一台机器、同一夹具（每条回执都提及 `s0`，即高重复来源）。旧版本每次查找
`.fetchall()` 物化全部候选，新版本惰性读取。旧版本按 20 次调用 / 1 次重复采样
（100k 候选下旧实现单次 56ms，200 次会拖长整轮），新版本 200 次调用、审计 3 次、
重建 5 次，取中位数与 p95。

| 规模 | 命中（旧） | 命中（新） | 未命中（旧） | 未命中（新） | 全量审计（旧/新） | 重建操作（旧/新） | 重建端到端（旧/新） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1k | 503 µs | **82 µs** | 38.8 µs | 111 µs | 29.3 / 23.4 ms | 10.5 / 9.9 ms | 17.0 / 15.6 ms |
| 10k | 4 434 µs | **75 µs** | 36.6 µs | 108 µs | 239.5 / 240.2 ms | 104.8 / 104.9 ms | 108.7 / 110.1 ms |
| 100k | 56 548 µs | **75 µs** | 38.8 µs | 109 µs | 2 380.7 / 2 332.9 ms | 1 139.2 / 1 117.5 ms | 1 105.9 / 1 107.9 ms |

指标含义（脚本头部同样注明）：`lookup` 是 `is_delivered(verified=True)`（模式维护快
路径 + 索引确认，不含重算回执哈希）；`statements` 是单次查找执行的 SQL 语句数
（命中恒为 4，旧实现为 3）；`incremental` 是无新回执时的 `verify_receipts()`；
`full_audit` 是重算全部回执哈希的 `verify_receipts(full=True)`；`rebuild_op` 是
`rebuild_receipt_index()` 本身（事务已开）；`rebuild_e2e` 是同一重建放在自己的
`BEGIN..COMMIT` 里，含提交。

结论：命中路径从"随候选数线性增长"变为常数（1k→100k 分别为 82/75/75 µs，语句数
恒 4），未命中路径为常数 108 µs，比旧版多约 70 µs，这是"未命中也要确认索引覆盖
整条链"的代价（多 3 条语句）。全量审计与索引重建维持线性，差异在噪声内。

## 后续修复：审计结论与派生结构的权威边界

上一轮 23 项用例没有覆盖"证据充分却不被采纳"的两条路径，补测时暴露：

1. **计数不一致被当成"区间变了"**。`audit_receipts_cached()` 在状态已确认
   （计数、链尾、回执尾三者一致）时，要求全量审计的 `head` 与 `count` 同时等于
   持久化值，否则 `receipt_audit_range_moved`。但 `head` 已经绑定位置、回执 id、
   摘要与前驱，同头即同一段历史；计数只是这段历史的摘要，而全量审计刚刚把它
   修对。结果是一次历史遗留的错误计数让每一次发布都失败，直到有人手动跑一次
   审计。现在只在**头**不一致时拒绝（区间确实变了），计数以审计结果写进检查点。
2. **恢复出来的游标替派生索引背书**。`_restore_receipt_state()` 只恢复状态行，
   不同步 `indexed_through`；若索引此前滞后或丢过行，恢复后的游标会让
   `is_delivered()` 认为索引"覆盖到链尾"，把缺失行读成"从未呈现"。现在恢复在
   同一事务里先重建索引、再声明覆盖；`is_delivered()` 遇到状态行缺失时先恢复
   再回答，而不是把 `chained_through` 读成 0 后拿它去比覆盖。
3. **丢失的状态行会让审计拿错头**。`audit_cache._chain_state()` 原先在状态行缺失
   时返回 `(GENESIS, 0, ...)`，于是全量审计走完整条链、却与 GENESIS 比较，
   一个可恢复的库被判成 `receipt_audit_failed`。现在先 `ensure_receipt_state()`
   重建（校验不过仍 `receipt_state_unrecoverable`），再拿真实头做判断。

`verify_receipts(full=True)` 顺带把恢复后的游标一并写回（同一次全量审计已经
证明它就是权威位置），不再只修计数。

新增用例：`test_receipt_state_recovery.py` 9 项（错误计数被修且检查点可复用、
篡改历史仍拒绝、丢失状态由审计重建、重建先于锚点比较、不可证明的链不修、
确认态审计换头被拒、恢复后索引先重建再判未命中、索引表被删可恢复、恢复后新
回执仍保持索引完整），`test_audit_cache.py` 2 项（发布在错误计数与丢失状态行
下都能成功，且随后命中缓存）。

```
py -3.11 -m pytest tests/test_receipt_state_recovery.py tests/test_audit_cache.py -q  # 46 passed
```

## 已知边界

- `is_delivered` 的未命中判定依赖"索引覆盖到链尾"这一结构事实；单行索引被删（覆盖
  标记仍为最新）不会在读路径被发现，需 `rebuild_receipt_index()`。
- 状态行丢失但链与回执不一致时选择报错而非修复：此时没有可信依据决定"哪一方是对的"。
- 全量测试里 9 项 `test_matrix_*` 失败是环境缺 `gui/node_modules`（playwright）导致，
  `test_command_containment` 的 1 项为偶发（单独重跑 3 次通过），均与本次改动无关。

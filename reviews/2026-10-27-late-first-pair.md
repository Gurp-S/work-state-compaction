# 晚位旧信息恢复：第一组 B/C 与未压缩基线

第一组完成：同一历史、同一问题，未压缩 U 为 2/2，原生 B 两次实际压缩后 1/2，WSC C 为 2/2。C 复用已完成行表资格结果，已知结果参与登记，因此本组是历史/前瞻混合的系统黑盒对照，不是三重复、严格算法因果实验或新优化整轮加速证明。

## 输入与评分

种子 20261028，320 个构建，前缀 641 个来源，旧目标 build-270 在来源 540；后续事件要求核对原始 nonce，当前构建变为 321。目标请求在第一压缩点后出现。问题均为同一结构化两字段查询，答案由预定义数据生成器确定，程序按字段类型和精确值评分，不使用关键词包含或额外 LLM 裁判。

|方案|旧 nonce|当前构建号|正确字段|
|---|---|---|---:|
|U 未压缩|正确|321，正确|2/2|
|B Codex 原生，两次压缩|回答无法取得原回执信息|321，正确|1/2|
|C WSC，两次选材，复用原结果|正确|321，正确|2/2|

B 没有编造随机 nonce，但未完成精确字段查询。回答失败不能直接证明原生内部摘要删掉了该信息；这里证明的是本次压缩后系统没有正确利用它。U 正确降低了“问题本身无法回答”的干扰，单次仍不能排除模型随机性。

固定 actor 为 gpt-6-luna / max，同一已登记 Codex 可执行文件 SHA；后测统一 120000 Token、4 响应、120 秒，权限和工作目录保持原登记。原生内部压缩模型、参数、采样种子、队列和缓存不可控，属于系统级比较。

从原 bootstrap 分叉，导入相同前缀，独立验证实际有效历史与 C 原 parent 的前缀相同（仅既有传输 ID/metadata/工作目录拼写标准化，正文、工具定义不变）；原生首次压缩后追加相同 delta，再第二次压缩。U 完整历史也验证相同，且历史/probe 的本地记录均无压缩事件。B 每次压缩均以 durable compacted 边界、绑定用量回执和 terminal 事件共同确认，不读取或解密摘要。

## 成本与计时

|方案|完整逻辑链调用 Token|响应数|模型阶段墙钟秒|本轮实际执行墙钟秒|
|---|---:|---:|---:|---:|
|U|62038|1|6.938|15.000|
|B 两压缩＋查询|145645|5|38.657|46.719|
|C 两选材＋查询（含复用 C1）|177645|4|92.218|不可直接配对|

本例 C 完整逻辑链 Token 比 B 多 32000（约 22.0%），得到一个额外正确字段。不能称为更省或更快，也不能由单个离散质量点推断等质量 Pareto 支配。相较 C 旧表示的 Token 改善见前一行表报告，是另一比较问题。

B 明细：第一次压缩 58636/1、8.469 秒，第二次 19093/1、6.532 秒，查询 67916/3、23.656 秒。U 查询 62038/1、6.938 秒。Token 包含已报告缓存 Token，不冒充金额；原生内部 Context 占用和不可观测成本仍未知。

C 这条接受链的 C1 是历史复用，C2+QA 也是上一轮结果；此前实际 C2-only 整轮 95.406 秒不含 C1，不能称为完整链总耗时。当前 B/U 的本地时序已记录；当前没有新的优化版 C 整轮计时，不能拿暖态微基准替代。冷热初始环境和服务时刻仍不同，不用这一组作优化收益因果结论。

本轮 B/U 并行两个 worker，总执行墙钟 46.719 秒，已知新增 207683 Token/6 响应。之前零模型准入 4.562 秒另计，不重复支付 C 的 177645 Token。封套 640000/16 为保守分配扣留，不等于已知实际花费，也不是未知用量上界；旧账和所有 unknown 保留。测试/维护未完整计时仍 unknown。

## 证据、复现与边界

原始目录 `D:/agent-task-runs/wsc-late-native-counterpart-20261027-v1` 包含 registration、B/U 实际请求/事件/rollout/phase 回执、两次压缩证明、逐项 JSON 时序及闭合结果。`independent-audit.json` 用零模型重新评分并检查两次真实压缩、六个唯一回执、ledger 对账、原始 DB/parent/旧 C 文件不变、所有拥有的进程清理确认。未压缩准入原目录 `D:/agent-task-runs/wsc-late-native-admission-20261027-v1` 保留，0 模型。

C 证据仍为 `D:/agent-task-runs/wsc-event-table-qualification-20261027-v1/candidate`，附该父目录 table-run-audit 和 candidate/source-tool-audit；不复制数据库和冷制品树。最新预算封套为新原生目录 `next-admission-envelope.json`：21891795 Token、372 响应、11592 秒；历史未知不重置。

执行入口（会产生新的模型花费，输出目录必须全新，不要重跑本组）：

```powershell
py -3.11 -B -X utf8 wsc/benchmarks/deterministic_v1/late_native_counterpart.py --source D:/agent-task-runs/wsc-late-recovery-qualification-20261027-v1 --reuse-c D:/agent-task-runs/wsc-event-table-qualification-20261027-v1/candidate --parent-envelope D:/agent-task-runs/wsc-late-native-admission-20261027-v1/next-admission-envelope.json --out <全新输出目录> --execute
```

只复核既有结果、不调用模型：

```powershell
py -3.11 -B -X utf8 wsc/validation/audit_late_native_counterpart_20261027.py D:/agent-task-runs/wsc-late-native-counterpart-20261027-v1
```

下一步补齐后两组，继续复用共同 C1，明确为“固定 C1 后重复 C2 续接”的条件实验，不能称为三条独立完整开发/选材链。新 C 启用已验等价的函数绑定优化与主机计时，保持模型输入协议不变；新 B 仍真实两次压缩。固定并发、记录先后与初始冷热资源，完整 Token 同时含共享 C1 逻辑成本与实际新增成本两个口径。完成三组前只报告本组有限观察，不宣称普遍超越原生。

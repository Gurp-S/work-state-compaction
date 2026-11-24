# 运行时去噪（runtime denoise）

把工具结果写进请求历史之前做一次确定性压缩，原文仍可通过 spill store 取回。入口在
`engine.js` 的 `tools/post-execute` 钩子，规则实现在 `lib/denoise.js`，设置页开关是
“工具输出去噪”（`client.js`，默认开启）。

## 触发条件

- 只处理成功的工具结果；失败结果保持原样。
- 文本长度在 1200–200000 字符之间才尝试压缩，更短的改写不划算，更大的会走 spill。
- 需要 spill store 才能保留原文；没有后端或写入失败时保持原文（fail-open）。
- 规则按顺序叠加：命令族 → 噪声行 → 重复行 → diff/JSON 摘要 → 头尾截断（含错误救援）。

## 机制清单

| 机制 | 做什么 | 什么时候省 | 边界 |
|---|---|---|---|
| `dedupe_reads` | 同一路径再次读取且内容哈希相同，替换为“与第 N 次调用相同”的指针 | agent 反复读同一文件、文件未变 | 文件一改哈希就不同，不会误折叠 |
| `dedupe_identical` | 任意工具结果与之前某次完全相同时折叠 | 重复执行同一条命令 | 仅全等时触发 |
| `dedupe_failures` | shell 失败输出按行归一化（ANSI、十六进制地址、UUID、耗时、`path:N`、`:N:N`、`line N`、百分比）后整段哈希，全等才折叠 | 同一失败反复出现（编译/测试循环） | 只折叠完全相同的失败集合；共享一行报错但其它行不同时不折叠 |
| `command_family` | 识别 pytest、npm、`node --test` / `*.test.*`、tsc、`git status/log/diff`，做结构化摘要 | 测试/构建/版本状态日志（几 KB 级） | shell 下 1000 字符即介入；pytest 保留失败与汇总；tsc 按文件分组并保留全部 `error TS`；`git diff` 原文透传 |
| `strip_noise_lines` | 去掉进度条、计时、纯空行等噪声 | 长时间运行的构建/下载 | 只删无信息行 |
| `collapse_stack` | 连续 ≥6 行完全相同折叠为 `×N` | 重复堆栈、重复警告 | 少于 6 行不动 |
| `diff_digest` | 大 diff 只保留文件与增删统计 | 巨型补丁 | 需要逐行内容时用 spill 原文 |
| `outline_json` | 大 JSON 只保留键结构 | 巨大的 API/配置返回 | 需要字段值时用 spill 原文 |
| `truncate_head_tail` | 保留头尾，错误摘录从被丢弃的中段救回 | 超预算日志 | shell 4000/1500 字符，非 shell 800/300；尾部已有错误时不重复摘录 |

## 实测收益

口径：本机真实会话的工具结果回放，`chars/4` 估算 token，仅计被改写的结果。

| 方案 | 省下的 token | 占原始比例 |
|---|---|---|
| native 内置剪枝 | 357,231 | 27.97% |
| native + 运行时去噪 | 396,246 | 31.03% |
| 去噪增量 | +39,015 | +3.06pp |

增量按规则拆分：`command_family` 235,173、`dedupe_reads` 105,845、`strip_noise_lines`
27,191、`truncate_head_tail` 24,942、`diff_digest` 3,100、`dedupe_failures` 0。

## 什么时候不省

- 输出本身很短（<1200 字符），或每条结果都不同。
- 需要逐字保留的 payload（二进制、精确补丁、长 JSON 字段）——规则不会改写，或会给出可回查的 spill 指针。
- 失败集合每次都不同（多一处报错就哈希不同），此时只做常规截断。

## 复现

```bash
node experiments/prod-matrix/denoise-savings.mjs native
node experiments/prod-matrix/denoise-savings.mjs v3r
```

结果落在同目录的 `denoise-savings-native-semantic.json` 等文件中。脚本只读本地已记录的日志，
不调用模型。

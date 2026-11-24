# 检查点格式

每个 `compaction/summary` 的文本就是检查点。由 `lib/passage.js` 按下面的顺序渲染，
`lib/checkpoint-budget.js` 给出字节预算；超预算时的让位顺序是
证据索引 → 观测值 → 账本（从未反过来先丢引用）。

```
Latest request: "…"                                   ← 长会话时置顶最新请求
User requirements (verbatim, in order):                ← 逐字、可编号
1. "…"
2. "…"
## Requirement coverage (mechanical)                    ← 可选，默认关闭
Ledger (current):                                      ← 按优先级排序的关系
- Decision: …
- Context: …
## Current state (model account; unverified)            ← done / open / next / unknown
## Recent changes
Checks: src/report.js was edited at #123; the check at #140 (npm test) reported: ok.
Observed values (fetch by key): [V1] …
Evidence index (fetch by key): [E1] … (read_evidence #214)
```

## 各区块的来源

| 区块 | 来源 | 是否模型生成 |
|---|---|---|
| 逐字需求 | 用户消息原文（`control` journal） | 否 |
| 账本 | 抽取模型返回的 `entries`/`revise`，逐条字面校验 | 是（唯一判定点） |
| 去噪折叠 | 渲染期按 subject 折叠旧版本、折叠重复测试计数 | 否 |
| 工作状态 | 编辑/测试回执 + 需求词匹配 | 否 |
| 检查行 | 回执：编辑序号 + 其后最近一次检查序号 | 否 |
| 观测值 | 工具结果里的常量行 | 否 |
| 证据索引 | 区域里的读/命令/编辑事件，带 seq | 否 |

## 可回查约定

- `edit #N` / `check #N` / `read_evidence #N` / `read_history #N` 都是**会话事件 seq**，
  不是区域位置。`receiptSeq: true`（默认）保证回执在写入 journal 时就是 seq。
- 账本超上限、索引被裁掉时，检查点会写明“还有多少条未展示”，并保留其 seq；
  恢复模型可以按序号取回，而不是猜测。
- 抽取失败的条目不会静默消失：检查点末尾的 `## Extraction gaps` 会列出原因计数。

## 去重与可见性

运行时 read-dedupe 会把重复读取替换成指针（`[denoise: …]`）。压缩发生时
`denoiseState` 被重置，所以压缩后的第一次重读返回真实字节，而不是指向已被
shadow 掉的旧结果——这是 2026-11-23 的 R1 修复。

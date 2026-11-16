# 一键评测包 (evals/)

三套评测的自包含运行包：**locomo**（长对话记忆）、**bench22**（陪伴型中文记忆 2.2）、**pair**（WSC vs DSH 原生压缩对比）。

## 一键运行

双击 `run_evals.bat` → 出现菜单 → 选 `1` 跑全部，或选 `2/3/4` 单跑某一套，选 `5` 演示逐题打印格式（不耗 API）。

每次运行都会实时打印：
- 每个子进程的**进度**（转发评测脚本 stdout）；
- **逐题结果**：`[PASS]/[FAIL] + score + 分类/题号 + 题目/测试名`；
- **分类汇总**与**总汇总**；
- 机器可读结果写入 `run_results/summary.json`。

## 首次配置（必做一次）

1. 复制 `config.example.json` 为 `config.json`（已内置一份，key 留空）。
2. 填 `api.api_key`（公司免费 API 的 key）。**config.json 已在 `.gitignore` 中，不会进仓库。**
3. 按需改 `api.base_url` / `api.model`（默认 `http://127.0.0.1:8788/v1` / `deepseek-v4.1-flash`）。
4. 换机器时改 `node.node_bin` / `node.dsh_cli` / `python.venv_python` 为实际路径；路径留空则回退到系统 `python` / `E:/nodejs` 默认值。

API 配置通过环境变量注入（`CSM_BENCH_BASE_URL`、`CSM_BENCH_MODEL`、`CSM_BENCH_API_KEY`、`WD_API_KEY`、`DASHSCOPE_API_KEY`），不改动任何评测源脚本。

## 三套评测说明

| 套件 | 入口脚本 | 逐题结果来源 | pass/score 字段 |
|---|---|---|---|
| locomo | `benchmarks/csm_locomo_plus.py` (`qa` / `cognitive`) | `run_results/locomo-*.json` 的 `records[]` | `judge.label` → correct=1 / partial=0.5 / wrong=0 |
| bench22 | `benchmarks/run_csm_bench22.py` (分 stage) | `.local/bench22-public-*/runs/**/judgments.jsonl` | 兼容 `pass`+`points` 与 `score`(float) 两套 schema |
| pair | `.local/goal-wsc-paid-20261111/host_pair.py` | `host-pair-*/{native,wsc}-result.json` | `score.tests[].ok`，汇总 `score.passed/total` |

### locomo
- `qa`（默认）：`--conversation N`，测指定对话。
- `cognitive`：`--samples N`，测 trigger/cue 子集。
- 数据在 `.bench/Locomo-Plus/data/locomo10.json`。

### bench22
- 分阶段执行：`prepare` → `gateway` → `exam` → `judge`（config 的 `bench22_stages` 控制）。
- `gateway` 阶段会起本地网关（端口 18892），由脚本内部处理。
- harness 与数据在 `.bench/chat-memory-benchmark-2.2/benchmark-2.2/`。

### pair（WSC vs DSH 原生压缩对比）
- 用 `prepare` + `run` 在隔离 stage `host-pair-auto/` 下跑，避免污染已有结果。
- **硬编码的 node 路径**：源脚本 `host_pair.py` 写死 `E:/nodejs`。driver 在运行时生成临时副本 `_host_pair.local.py`，仅替换 `NODE`/`CLI` 两行为 config 中的路径，跑完即删，不改动交付脚本。
- 注意：18/18 但 exit≠0 可能是尾部综述被 token cap 截断，需看六指标报告，不能只看通过数。

## 目录结构

```
evals/
  run_evals.bat            # 一键启动（菜单）
  eval_driver.py           # 主编排 + 逐题打印 + 汇总
  config.example.json      # 配置模板
  config.json              # 你的本机配置（含 key，不提交）
  README.md
  src/wsc/                 # wsc.csm 运行依赖（含最新 CSM，64 个 py）
  benchmarks/              # locomo + bench22 脚本（70 个 py）
  .bench/                  # locomo / bench22 数据
  .local/goal-wsc-paid-20261111/   # pair 评测脚本
  dsh-wsc/                 # pair 用的 JS 插件（最新，含未提交改动）
  run_results/             # 运行结果（gitignore）
```

## 命令行（可选）

```bash
python eval_driver.py                 # 按 config 跑全部
python eval_driver.py --only locomo   # 单跑 locomo
python eval_driver.py --demo          # 用已有结果演示打印格式，不耗 API
```

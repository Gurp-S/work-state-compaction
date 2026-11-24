# 评测 harness

当前主线评测在 `prod-matrix/`。它用 headless dsh 跑脚本化仓库任务，把每轮的输出
写成 `out/round-NN.jsonl`，最后汇总到 `summary.csv`。

## 需要的目录

```
prod-matrix/
  matrix.py queue_runs.py …      harness
  scenarios/<场景>/rounds.json   每轮用户消息
  scenarios/<场景>/seed/         起始工作区
  scenarios/<场景>/probe.json    末轮严格探针
  runs/<场景>/<臂>/rep<N>/       ！运行产物，不入仓库
    done                        该次运行的 session id
    ws/                         最终工作区
    out/                        逐轮 jsonl 与 stderr
    metrics.json                成本、压缩次数、检查点、测试、探针
```

`runs/` 是本地数据（每次长跑会生成几十 MB 的工作区和会话快照），
`.gitignore` 已排除。场景与 harness 会随仓库提交，便于复跑。

## 环境变量

| 变量 | 用途 | 缺省 |
|---|---|---|
| `DSH_HOME` | dsh 状态目录（session / journal / 用量） | `~/.dsh` |
| `DSH_CLI` | headless 入口（`dsh.cmd` / `dsh`） | `dsh`（PATH） |
| `DSH_NODE_EXE` | desktop 的 Node 可执行文件 | 空 |
| `NEW_API_KEY_FILE` | 一行 API key 的文件；不设则沿用进程环境里的 `NEW_API_API_KEY` | 空 |

`DSH_HOME` 同时决定 session（`sessions/`）与 WSC journal（`wsc/nosig/`）的位置；
`final-corrected.py`、`arm-deep.py` 等分析脚本也读它。

每臂的 profile 由实验室脚本从 `$DSH_HOME/profiles/` 复制生成，未随仓库提交；
运行时的最终 wsc-config 见 `../过往实验/<实验>/configs/`。

## 常用命令

```bash
# 预算（不调用模型）
python matrix.py plan --repeats long-40=2 --arms v3r --jobs 2

# 运行：--jobs 建议 3–5；更多并发会触发上游 429
python matrix.py run --repeats long-40=2,constraint-25=1 --arms v3r --jobs 3

# 混合队列（不同臂不同重复数，共用一个并发池）
python queue_runs.py --jobs 5 --spec "long-40:v3r:1-8,long-40:native:1-8"

# 汇总已有 run 目录
python matrix.py analyze
```

## 指标口径

- `totalCostCny = 主会话 step 成本 + 抽取成本`。原生臂没有抽取，但它的压缩调用
  usage 记在 session 的 `compaction/summary` 事件里，**`matrix.py analyze` 不会自动加**；
  公平对照用 `final-corrected.py`（它会把 summary 调用计入 native，并对 w80 早期
  缺 usage 的样本做估算）。
- `checkpointChars` 是每次检查点的字符数；末值用于比较增长边界。
- `probePassed/probeTotal` 只读末轮回答的 must/forbid，不从工具结果取词。
- `oracle-long40.py` 直接给最终工作区打分（54 项：源码、README、CHANGELOG、
  测试内容、CLI 行为）。
- `arm-deep.py` 补充原文层指标：压缩率、逐字需求保留、引文可解析、需求覆盖、
  重读、返工、越界编辑、违规编辑、环境路径泄漏。

## 场景

- `long-40`：40 轮连续改造一个 orders-report CLI（加税、限额、CSV、JSON、
  rounding、分类、CHANGELOG…），第 15/20/21/23/33 轮明确“不要改源码”。
- `constraint-25`：首轮写入 BLUEBIRD 并要求“后续所有改动保留它”，末轮禁止读文件，
  考早期约束与事实保留。
- `feature-25`、`refactor-18`、`bugfix-16`：早期短场景，保留作回归。

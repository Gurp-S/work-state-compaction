# 评测程序（bench22）

评测程序负责四件事：**记忆隔离**、**成本计量（含成本上限）**、**答题与判分**、**泄漏哨兵**。参赛系统只需要实现两个函数（自然用记忆榜再加两个）。

```text
bench22/
  gateway.py      计量网关：持有供应商密钥，按 prices.json 给每次调用计价；一次运行的全部调用（系统自己的 + 答题 + 判分）按价目表累计，到 run_cost_ceiling_cny（score_config.json，默认 ¥50）即 403 RUN_COST_CEILING，运行停止、无成绩
  systems.py      适配器接口 + 参考系统（qwen-base、none、recent6、bm25-recent6、full-context、vague，自然榜的极端基线 never-recall / always-recall）
  runner.py       评测程序：按截止轮喂历史、检索、答题、判分、汇总（日常分 D、长期分 L、A、聚类 bootstrap 区间）；--sentinel 跑泄漏哨兵
  natural.py      自然用记忆榜：run / judge / confirm / summarize（尾巴、回退、多轮现场生成、判分、子分、区间、X 诊断）；--sample N 只跑按类比例抽样的 N 题
  scoring.py      通过规则、计分单元（成对题）、D / L / A、bootstrap、成本 C、综合分 S（系数在 score_config.json）
  report.py       从运行结果生成榜单：A、区间、C、S、总排名（短 25% + 长 25% + 自然 50%）
  plot.py         成绩—成本散点图（SVG）
  prompts/        判分提示词（SHA 写进每条判分记录）
  prices.json     固定价目表（带版本号）
  score_config.json  系数、权重、参照系统、成本上限
```

## 适配器接口

```python
from bench22.systems import System, Retrieval, Gateway

class MySystem(System):
    name = "my-system"
    def __init__(self, gw: Gateway): ...        # gw 是网关客户端；所有模型调用都走它
    def ingest(self, turn):                     # turn = {"turn":int,"time":iso,"user":str,"assistant":str}，严格按顺序，一轮一轮喂
        ...
    def retrieve(self, question, now, cutoff_turn, item_id=None) -> Retrieval:
        # 只读！返回要塞进答题提示词的记忆文本 prompt（它的 token 会按 flash 输入价计入 C）
        return Retrieval(prompt, used_turns=[...])
    # 自然用记忆榜还需要：
    def mark(self): ...                         # 返回当前记忆状态的标记（默认：已喂入的轮数）
    def rewind(self, token): ...                # 丢掉标记之后喂入的内容（尾巴、多轮题里现场接上的回复）
```

评测程序保证：访问某个考点时，系统已经 `ingest` 的恰好是截止轮及之前的全部历史；考点按截止轮从小到大访问；返回的 `used_turns` 里出现截止轮之后的轮次直接记为泄漏。

## 成本上限

一次运行的总费用（你的系统的写入 / 检索 / 内部对话调用，加上评测程序的答题和判分，全部按价目表）累计到 ¥50 就停止，这次运行没有成绩，押金不退、也不再多收。上限的累计按账本重建，重启网关不会清零。网关用评测程序独有的令牌区分评测程序自己的调用和参赛系统的调用（账单分三项列出：系统 / 答题 / 判分）：网关和评测程序进程设环境变量 `BENCH22_EVAL_TOKEN`，参赛系统运行在没有这个变量的环境里。测试：`tests/test_bench22.py`。

## 网关

```bash
export DASHSCOPE_API_KEY=...        # 向量 / 重排（Bailian）；对话模型的密钥见 gateway.py 顶部的环境变量说明
python -m bench22.gateway --port 18877 --cap-usd 9.5
export OPENAI_BASE_URL=http://127.0.0.1:18877/v1
```

路径：`/v1/chat/completions`、`/v1/embeddings`、`/v1/rerank`。请求头 `X-Bench-Phase`（ingest / retrieve / answer / judge）、`X-Bench-Tag`、`X-Bench-System` 用于记账。网关带花费硬上限。本地模型：在网关上设 `BENCH22_LOCAL_URL`，系统里以 `local:模型名` 调用，按 DeepSeek flash 的价格计价并计入上限。

## 跑一遍

```bash
python -m bench22.runner --release ../dataset --system bm25-recent6 --split dev --run mine           # 开发集
python -m bench22.runner --release ../dataset --system bm25-recent6 --split dev --run mine --sentinel   # 泄漏哨兵（只检索）
python -m bench22.report --release ../dataset --run mine --split dev --out out/
python -m bench22.natural run --release ../dataset --natural ../dataset/natural --system bm25-recent6 --split dev --run mineN
python -m bench22.natural judge ... ; python -m bench22.natural summarize ...
python -m unittest discover -s ../../tests -p "test_bench22*.py"                                       # 离线单元测试，不需要密钥
```

封存集只在评分时由评测方持有；`--split sealed` 需要封存集目录。更多见 [../README.md](../README.md)。

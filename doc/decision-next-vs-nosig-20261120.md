# 决策记录：`wsc_next` 不取代 `wsc_nosig`（2026-11-20）

- 状态：已决（2026-11-20 完成同契约复核，见第九节）
- 决策：默认版本保持 `wsc_nosig`；`wsc_next` 保留为可选呈现臂，不升级为默认。
- 判据：同成功率下成本是否有可复现优势；差异落入噪声区即视为无收益（见[优化停止线](../docs/optimization-stop-line.md)）。
- 关联：[WSC v1 冻结清单](wsc-v1-freeze-20261120.md)、[重复采样实验记录](wsc-repeat-sampling-20261119.md)。

## 一、问题

`wsc_next` 只比 `wsc_nosig` 多一行独立的 `Next action` 呈现（[passage.py:40](../src/wsc/passage.py#L40)），压缩与恢复契约完全相同（[resume.py:390](../benchmarks/coding_compaction_v1/resume.py#L390)）。需要判断：它是否应取代 `wsc_nosig` 成为默认。

此前的 C 实验只有 5 次采样，DeepSeek 两组符号相反，GLM 略升，无法定论；本轮把样本补到短用例 30 次、stale-next 25 次、长用例 10 次，并修掉一处评测夹具缺陷后复核。

## 二、行为证据

两臂在全部用例上 success 与 required 相同，违规为 0：

| 用例 | 模型 | 样本 | `wsc_nosig` | `wsc_next` |
| --- | --- | --- | --- | --- |
| recorded-next-step | DeepSeek | 30 | 30/30，extra 1 | 30/30，extra 1 |
| recorded-next-step | GLM | 30 | 30/30，extra 11 | 30/30，extra 12 |
| stale-next | DeepSeek | 25 | 25/25，extra 23 | 25/25，extra 21 |
| stale-next | GLM | 25 | 24/25，extra 23 | 25/25，extra 24 |
| recorded-next-long（旧夹具） | DeepSeek | 10 | 10/10，extra 0 | 10/10，extra 0 |
| recorded-next-long（旧夹具） | GLM | 10 | 10/10，extra 16，重做 8 | 10/10，extra 17，重做 8 |
| recorded-next-long（修复夹具） | GLM | 10 | 10/10，extra 2，重做 0 | 10/10，extra 3，重做 0 |

GLM 在 stale-next 的唯一一次失败是第 5 次样本返回空动作，归因为模型侧单样本，不是机制差异。

## 三、成本证据

按同一样本的检查点成对比较恢复成本（next 减 nosig），全部 95% 区间跨 0：

| 用例 | 模型 | 差值均值 | 95% CI |
| --- | --- | --- | --- |
| recorded-next-step | DeepSeek | −0.0012 | [−0.0036, +0.0013] |
| recorded-next-step | GLM | −0.0073 | [−0.0170, +0.0025] |
| stale-next | DeepSeek | −0.0023 | [−0.0058, +0.0012] |
| stale-next | GLM | +0.0008 | [−0.0122, +0.0138] |
| recorded-next-long | DeepSeek | −0.0002 | [−0.0012, +0.0009] |
| recorded-next-long | GLM | −0.0053 | [−0.0241, +0.0136] |
| recorded-next-long（修复夹具） | GLM | −0.0070 | [−0.0186, +0.0045] |

压缩成本两臂相同：next 与 nosig 共用同一份压缩输出。汇总里 next 的压缩成本显示为 0 是缓存复用，不是真实节省。按“nosig 压缩 + next 恢复”折算，修复夹具后的 GLM 长用例总成本为 ¥0.0537，对照 nosig 为 ¥0.0607，差值仍落在区间重叠内。体积上 next 多一行 banner，约 +0.3%（1749B → 1755B）。

## 四、夹具缺陷的更正

旧数据里 GLM 长用例 8/10 重做 `src/flags.py`，一度被怀疑是模型缺陷。回放证明这是评测夹具错误：第 0 轮编辑返回 `ok`，但夹具里该文件仍是 `FEATURE_OLD`（修复后的定义见 [resume_cases.py:368](../benchmarks/coding_compaction_v1/resume_cases.py#L368)）。GLM 按检查点的 `unknown: check at #81 is synthetic; it does not verify src/flags.py`（[live.py:1469](../benchmarks/coding_compaction_v1/live.py#L1469)）去核验，读回旧内容后按证据重新执行改名；DeepSeek 不核验，所以不复现。修复为 `FEATURE_X = "FEATURE_X"` 后，两臂重做都从 8/10 降到 0/10，extra 从 16/17 降到 2/3，证明重做是夹具造成，不是 `next` 与 `nosig` 的差异，也不是 GLM 的推理缺陷。

## 五、结论与理由

1. 行为上，两臂等价；`next` 没有减少漏做，也没有增加违规。
2. 成本上，所有成对差异区间跨 0；折算后的总成本差异同样落在重叠区。按停止线，视为无收益。
3. 呈现上，`next` 只是把 State 里已有的 `next` 行单独提前显示；检查点因此略大，但未改变任何决策。
4. 唯一曾被归因于 `next` 的 GLM 重做，已证明来自夹具，不是呈现方式。

因此 `next` 是一个“不劣、无增益”的呈现变体，没有理由替换默认。默认保持 `wsc_nosig`。

注：本节的成本与推理结论基于被混淆的数据，已被第九节的同契约复跑取代；行为与成功率的对照仍有效。

## 六、什么情况下重新考虑

- 出现真实会话中 `next` 行被更长的 State 淹没、且 `nosig` 可复现漏做的证据；
- 或出现跨多次压缩循环（不止一次阈值压缩）的长程用例，能稳定区分两臂；
- 届时按同一判据补重复采样，成本差异仍需脱离噪声区。

## 七、影响

- 默认臂不变；`wsc_next` 状态从“暂不默认”更新为“已裁定不取代”，仍可用于呈现消融。
- 仅修改评测夹具 [resume_cases.py:368](../benchmarks/coding_compaction_v1/resume_cases.py#L368)；引擎、契约、默认路径未改。
- 离线检查（self-check、stopline、acceptance）全部通过。

## 八、证据目录

- 短用例与 stale-next：`resume-20261120-003526`、`095430`、`095434`、`105512`、`105515`
- 长用例（旧夹具）：`resume-20261120-095437`、`095440`、`105519`、`105520`
- 长用例（修复夹具，旧契约）：`resume-20261120-135739`
- 同契约复跑：`resume-20261120-142254`（DeepSeek 10 次）、`resume-20261120-142243`（GLM 3 次，按时间收口）
- 推理原文回放：`runs/quality-probe-deepseek.log`、`runs/quality-probe-glm.log` 及同名 JSON
- 归因回放：`runs/why-model2.log`、`runs/why-model3.log`、`runs/why-model3.json`
- 变体复跑：`runs/next-cause-glm2.log`、`runs/next-cause-glm2.json`

## 九、补记：提示词混淆（2026-11-20）

复核原始数据时发现，`wsc_next` 没有登记在 `RESUME_V2_ARMS`（原 [resume.py:53](../benchmarks/coding_compaction_v1/resume.py#L53)），因此它一直使用旧的短恢复提示（3 条规则），而 `wsc_nosig` 使用条件化的 6/8 条契约。也就是说，上文所有“next 对 nosig”的差异同时包含了两处变化：banner 与更短的恢复契约，无法把成本或推理变化归因于 banner。

该混淆已修正：`wsc_next` 现已加入同一契约集合（[resume.py:53](../benchmarks/coding_compaction_v1/resume.py#L53)），并在 `resume.py --self-check` 中增加断言，保证两臂的恢复提示完全相同、仅检查点呈现不同。

同契约复跑结果：

| 模型 | 样本 | `wsc_nosig` | `wsc_next` | 恢复推理（均值） |
| --- | --- | --- | --- | --- |
| DeepSeek | 10 | 10/10，extra 0 | 10/10，extra 0 | 1362 → 1052 |
| GLM | 3 | 3/3，extra 1 | 3/3，extra 1 | 6645 → 9029 |

DeepSeek 的恢复成本配对差为 −0.00132，95% CI [−0.00258, −0.00007]，折算总成本 ¥0.0429 → ¥0.0415（约 −3%）。GLM 三组样本方向相反，其中一组恢复推理从 9.2k 升到 15.9k，均值反而 +36%。

独立回放思考原文（同一检查点、同一契约）：

- GLM 3 对：next 平均 9121 思考 token、不确定措辞 102 次；nosig 为 7366、89 次。
- DeepSeek 5 对：next 平均 1365、13.6 次；nosig 为 1203、11.4 次。
- 两模型的回放方向与整轮运行也不一致（DeepSeek 整轮 next 更低，回放 next 更高），说明差异主要是采样噪声，而不是 banner 的稳定作用。
- 观察到一次 next 的副作用：模型在仍需核验时把 `edit CHANGELOG.md` 和 `read src/flags.py` 放在同一轮，编辑被 harness 丢弃后又在下一轮重发，反而多一轮推理（GLM r1）。最终输出两臂都正确。

结论不变：banner 没有稳定减少“推断下一步”的推理；在这批用例里，`next` 行在 `nosig` 的 State 中本来就单独可见，可供推断的空间很小。默认仍用 `wsc_nosig`，`wsc_next` 作为可选呈现臂保留。只有当日志出现“next 被大量 State 条目淹没、nosig 可复现漏做”时，才值得为 banner 单独立项验证。

## 双向链接

- 出链：[WSC v1 冻结清单](wsc-v1-freeze-20261120.md) · [重复采样实验记录](wsc-repeat-sampling-20261119.md) · [今日目标（11-20）](goals-20261120.md)

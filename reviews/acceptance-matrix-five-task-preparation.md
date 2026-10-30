# 五任务程序验收校准（尚非 B/C 结果）

2026-10-28。用户已确认固定相同密封历史检查点、事后记录实际 Token，属于系统级黑盒比较；强档 gpt-6.1-sol/max，弱档 gpt-6-luna/max。原验收矩阵未修改，执行修订 v1.1 继续有效。

|任务|程序验收|参考实现|缺陷 starter|
|---|---:|---|---|
|T1 重试修复|11|全部通过|11 项失败（历史 v1.45 校准凭据）|
|T2 API 迁移|13|严格 TypeScript 编译及 12 项运行检查通过|类型检查失败；12 项运行检查未执行|
|T3 数据库迁移|10|全部通过|10 项失败（历史 v1.45 校准凭据）|
|T4 UI 功能|13|真实 Chromium 交互全部通过|12 项失败，1 项通过|
|T5 多阶段产物|11|全部通过|11 项失败|

58 项是五个参考实现的程序断言数量，不是模型正确率、模型运行数或原生对比结论。T1/T3 沿用具名旧校准，未重复执行；T2/T4/T5 是本次新增校准。

T2 实际检查所有调用方的类型及行为，包括 provider/model 配对、分页完整性和查询边界。T5 实际读取规范化、汇总、manifest 文件，校验原始输入哈希、跨阶段关系、精确整数金额、重放与失败后的已发布状态。T4 检查 provider 筛选、零值/缺失/未定价、筛选后汇总、空数据/不可用、失败保留旧数据、请求竞态、筛选失效重置、销毁后回调、字面文本及窄屏范围说明。

T4 保存真实旧版与参考版截图；没有主观美观评分。大型 JSON 配置与旧截图均是公开历史，明确标为旧版本，不作为当前代码通过证明。合成历史里的日志是本地实测日志的重放，不冒充模型经历过的失败尝试。

## 校准错误及修复证据

T4 v1 的参考实现有 4 项被误判：HTML output 具有隐式 status 角色，验收器按角色查询时同时匹配状态提示和汇总。结构性原因是没有区分契约中显式状态节点与隐式 ARIA 角色；规则改为定位契约声明的显式 role=status，保留独立的汇总断言。v1 失败目录原样保留，v2 全部通过，另有回归检查验证二者不再冲突。此修复只改评测器，没有改 WSC 或原生 Codex。

新增验收器自测：T2/T5 9 项、T4 4 项通过；四任务及随后五任务的历史边界检查分别通过 5 项。错误实现覆盖漏更新调用方、同名模型跨 provider 混合、导出只有第一页、浮点金额、替换解码、错误阶段引用、provider 折叠、旧请求覆盖新结果、销毁后仍渲染。原始日志位于 acceptance-matrix-admission-20261028，未将“未执行”改记为错误或成功。

## 数据与复现

- T1/T3：`D:/agent-task-runs/wsc-matrix-task-admission-20261028-v2`
- T2/T5：`D:/agent-task-runs/wsc-matrix-t2-t5-admission-20261028-v1`
- T4 当前：`D:/agent-task-runs/wsc-matrix-t4-admission-20261028-v2`；评测器误判的 v1 另存未删除。

每任务保存公开起点、配对历史、原始公开 smoke、私有答案、参考校准和内容哈希清单。统一准备入口复用现有 Python、Node、TypeScript、Playwright、Chromium，无依赖安装。工具版本及可执行文件指纹见 `acceptance-matrix-admission-20261028/task-toolchain.json`；任务源码指纹另存 task-source-manifest.json。

```powershell
py -3.11 -B -X utf8 wsc/validation/prepare_matrix_tasks.py --tasks T2 T5 --out <新的空结果路径>
py -3.11 -B -X utf8 wsc/validation/prepare_matrix_tasks.py --tasks T4 --out <另一个新的空结果路径>
py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_matrix_t2_t5_acceptors.py -v
py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_matrix_t4_acceptor.py -v
py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_matrix_task_histories.py -v
```

以上命令在仓库根目录运行；不会调用模型。旧 prepare_matrix_t1_t3.py 保留兼容入口并委托统一准备模块，没有复制第二套准备逻辑。

## 准入边界与下一步

当前新增模型推理 0、付费任务 0。五个验收器已本地校准，但任务未通过真实完整历史 A / 最后状态控制；不能仅靠引用或枚举回忆失败宣称任务依赖历史。私有目录分离也不等于宿主工具权限隔离。当前 registration.draft 仍不可派发，all_five_tasks_ready=false。

下一步完成共享运行器的权限隔离、密封历史的真实原生接收、压缩发生确认、恢复工具计数与原子预算准入；冻结六轮事件更新和检查点分母。满足对应闸门后，直接执行已授权的强档 T1 完整历史 A / 最后状态控制，再做 B′/C 第一对，证据费用闭合后补齐 3 重复。首批总上限仍 2M Token / 64 响应 / 3600 秒、最多 2 臂并行，旧失败、费用和 unknown 保留，不追加总预算。

不从这些校准推出 WSC 收益；原生 B 的算法、默认触发和实现保持不变。

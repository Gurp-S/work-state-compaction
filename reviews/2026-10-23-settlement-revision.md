# 发布结算修订：准入与已提交事实分离

范围：独立 WSC 的发布/恢复实现；不改变模型材料、选材、触发、原生执行器或语义判断。

## 根因与不变量

旧实现把“候选此刻可以首次安装”的 epoch 条件再次用于“宿主已经持久安装”的结算。新控制或理解到达后，该历史提交永远无法结算。另一个入口把迟到异常无条件写入操作行，能覆盖另一恢复调用已确认的结果。

统一规则是：提交前按当前状态准入；提交后按该操作的可信宿主持久结果结算。没有结果就保留未知，不能重复安装。已确认的终态不可由迟到响应或中断降级。

宿主仍负责在安装的原子边界校验控制/容量/来源条件并保存真实回执；本改动不从文件导出或摘要完成推导安装成功。

## 实现边界

- 新逻辑放在独立 `src/wsc/settlement.py`，由现有发布入口调用。
- 首次安装的 `check_binding` 与 `check_evidence` 保持。
- 回执仍须匹配 operation、package digest、session、workspace、generation、安装时 control_epoch、through、receiver 与证据可用性。
- 结算仍检查本地代次与不可变来源前缀，允许提交后正常到达的新控制/理解。
- `confirmed/rejected` 不被异常处理覆盖；保留 BaseException 的清理和重新抛出行为。
- 不删除未决操作、来源、理解或旧回执；不引入轮询重试或任何模型调用。

## 版本与验证

修复前源码及既有回执保存为 `versions/20261023-pre-settlement.zip`，70 个文件，139957 字节，ZIP SHA-256 为 `fb48a3a435af55edc6bf8e4366602118d5fb2c382fbb8ab59bb9dfc8ac820abf`，逐文件哈希已回读核对。

修复前原有测试 65/65 通过，说明旧“卡死测试”没有阻止缺陷。改为成功恢复断言并增加真实持久宿主交错用例后，修复前 7/7 失败：4 个 epoch 卡死错误、3 个终态降级失败。具体名称与当前源哈希在 `validation/publication-settlement-20261023/counterexamples-before.json`。

同样 7 个反例在修复后 7/7 通过，完整独立包检查 71/71 通过。回执为 `validation/publication-settlement-20261023/counterexamples-after.json` 与 `suite-after.json`，各自包含运行时、测试和实验驱动的逐文件 SHA-256；明细保存在同名 `.txt`。未运行模型。

离线宿主交错验证不等于 DSH 实接或原生事务安装验证，也不证明语义收益或超越原生。后续代码变化不能沿用此回执宣称新版本已全部验证。

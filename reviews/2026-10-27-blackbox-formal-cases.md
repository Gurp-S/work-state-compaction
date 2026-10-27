# 黑盒正式案例准备：尚未执行比较

代码级修复后，继续原来的黑盒评测方向。没有重启旧长程开发实验，也没有重跑两事实资格探针。本轮新增模型调用0。

新增`benchmarks/deterministic_v1/blackbox_matrix_cases.py`，提供五组可复现案例：

- authority：高优先级禁止与后来的低优先级允许冲突；同优先级最新状态覆盖。
- version-relations：源版本、制品ID和已测版本分别更新，验证关系不能靠单字段正确冒充。
- task-switch：活动任务切换时，其他任务暂停/完成状态独立保留。
- long-distance：早期随机标识与路径经过日志和其他任务的相似字段干扰后查询。
- expiry-recovery：租约存在明确失效间隔，分别查询当前状态和过去有效状态；未用连续续租冒充失效测试。

公开协议给出时间有效期、优先级、同优先级序号覆盖和版本验证关系。它们是任务规则，标准答案不是从模型输出中抽取。私有oracle与公开历史分开；模型材料不包含问题或expected字段，后续所有分支使用相同问题。对自由文本语义没有扩展评分声明。

独立程序在测试里从公开事件按规则解析状态，交叉核对预定义oracle；反例检查拒绝约束反转、失效租约与错配的制品关系。12项框架检查通过，凭据`D:/agent-task-runs/wsc-blackbox-formal-cases-20261027-v1/scoped-tests.xml`。首次测试中把5轮租约预期误写成null，独立规则检查发现，修正为奇数轮有效、偶数轮失效，保留此说明。

计划已生成在`D:/agent-task-runs/wsc-blackbox-formal-cases-20261027-v1/matrix.json`：seed=20261027，每组3次重复、5个检查点，共75个配对单元，每个单元包含未压缩/native/WSC三分支。重复之间材料与问题hash相同，用于观察系统随机性；随机种子控制数据生成，不声称控制模型采样。计划不是75次已执行实验。代码支持5/10/20/50检查点数据生成，不声称执行过这些轮数的真实压缩。

复现：

```powershell
py -3.11 -B -X utf8 wsc/benchmarks/deterministic_v1/blackbox_matrix_cases.py --out D:/agent-task-runs/wsc-blackbox-formal-cases-unique --seed 20261027 --rounds 5 --noise 80 --repeats 3
py -3.11 -B -X utf8 -m pytest wsc/tests/test_blackbox_matrix_cases.py wsc/tests/test_blackbox_benchmark.py -q
```

下一步把既有真实原生压缩、WSC选材/导入和预算清理代码接入统一矩阵执行器。先无模型验证：问题只进入兄弟探测分支、主干不受答题污染、私有oracle不进入运行环境、同输入hash与费用闭合、失败样本保留。运行时仍须核验隔离，当前文件分目录本身不是安全隔离证明。之后先执行第一组3次正式配对并报告，再扩展其余组，避免直接发起整个矩阵。

原生压缩必须有真实compacted记录、绑定用量收据和完成事件；WSC必须走正常选材/恢复机制。不可观测内部上下文Token、压缩模型参数和恢复成本继续unknown；不以字节数冒充Token，也不以这套准备材料宣称任何收益。

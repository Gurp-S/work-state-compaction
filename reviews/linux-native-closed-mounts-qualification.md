# 同版本 Linux 原生与闭集挂载准入

更新2026-10-30，工作跨日；实验目录保留20261029命名。延续 v1.66，不重跑旧模型对照，不增加研究预算，本轮没有模型请求。原生算法与二进制未改。最终 WSC 目标未完成。

## 为什么更换边界机制

Windows原拒读目录及额外文件deny均无法阻止读取同一旧A代码。具体原生权限/ACL根因尚未完整定位，但旧结果已证明“配置存在”不足以保证拒读。继续增加路径没有收益依据。

新旁路将原生进程放入Linux外层文件系统：只挂载所需系统工具、只读原生运行文件和本臂独占工作树。宿主盘、其他臂、评分器、旧答案均不挂载；单独PID及网络命名空间阻止通过普通宿主路径或宿主进程根目录直接访问。原生自己的工具沙箱仍照常执行，未用自制压缩器替代Codex。

这是旁路环境机制，不是默认WSC行为，不是已完成的付费评测系统。闭集挂载的规则可结构性减少漏登记旧答案目录的风险；当前证据只覆盖声明的挂载与读取，不宣称不存在内核漏洞、全部网络或服务访问风险。

## 运行文件与来源

旧Windows对照版本号为0.165.0-alpha.1.2。本轮找到相同版本的官方@openai/codex发布元数据，Linux x64包具有同版本变体，而非自动改用最新版。官方安装脚本读取超时，失败记录保留，没有执行该脚本；之后按固定版本获取发布包，不运行npm安装脚本。

下载166011963字节，与包元数据的SHA-512 integrity完全匹配。只提取codex、code-mode-host、rg、bwrap及package元数据，共5文件392694279字节，未提取语音组件。每份文件有SHA-256。完整性是与所取得发布元数据对应的传输校验，不冒充额外签名或供应链审计。原生运行文件只存于wsc-tools一次，不进入增量版本包。

同版本号不意味着跨架构字节相同。OS、工具及启动环境仍有变化，两臂的新运行必须共同绑定这些变量；旧Windows数据只能作历史参照。

[官方CLI安装入口](https://learn.chatgpt.com/docs/cli)与[官方App Server协议](https://learn.chatgpt.com/docs/app-server)确认了Linux安装及初始化、历史注入、版本化schema和压缩接口的公开入口；本轮没有调用压缩。可行性结论来自下面的实际原生请求，不以文档代替测试。

## 实际运行与结果

Docker Desktop启动在本轮超时退出，API仍不可用、WSL发行版停止，失败保留。该等待没有归给WSC压缩时间。未循环重启Docker或安装新服务。

已有docker-desktop WSL发行版能直接启动Linux二进制。因此先做无外层文件系统的协议探针，再用官方包自带bwrap做外层边界原语检查，最后在该边界内检查实际原生协议和已知私有文件。不依赖Docker后台，不生成新镜像。

|检查|实际结果|范围|
|---|---|---|
|Linux codex --version|0.165.0-alpha.1.2|真实二进制执行|
|原生initialize / thread/start|通过|gpt-6.1-sol/max、无fallback|
|WSCSource动态schema注册|通过|没有模型调用或工具恢复行为|
|thread/inject_items|通过|物理rollout中观察到合成消息，未出现token_usage_record|
|原生command/exec|通过|真实shell输出与退出码核对|
|外层边界内上述原生协议|通过|UID65534、独立命名空间、清空环境和新HOME|
|31份宿主真实存在的私有材料|全部测试路径不可读|64种路径，含直接宿主和/proc/1/root形式及socket|
|挂载生成器4项检查|通过|宽泛宿主根、相对/越界路径、重叠、可写挂载边界|

31份文件先在宿主确认存在并绑定当前SHA，不用“宿主文件本来不存在”制造拒读成功。实际原生命令尝试读取后只返回成败标记，不把答案内容放进探针输出。v1外层探针仅4路径；v2扩展到完整旧31文件及逃逸路径，不把二者当独立模型重复样本。原v1/v2、失败及源码快照均保留。

原生进程只收到initialize、initialized、thread/start、thread/inject_items、command/exec。传输程序拒绝其余方法；没有turn/start或thread/compact/start。模型、调用成本和任务质量没有新增数值。本轮不是黑盒任务收益对比。

外层原语检查只挂只读运行文件；实际协议检查另外挂载新建actor-root为/work，协调器输出和旧材料在挂载外。首次协议探针没有外层文件系统，绝不作为安全执行环境。清理终止本轮从停止状态自行启动的WSL发行版，进程及发行版没有留在后台。

## 不应混淆的未完成项

- 64路径不可读，不等于已证明所有网络、MCP或内核访问都不可行。当前网络隔离关闭外网，尚不能运行真实提供方调用。
- 注册WSCSource不等于正常回查成功。真实来源reader、发布包、线程/工作区绑定及回调恢复尚未接进此Linux会话。
- 需要显式处理宿主工作树路径与Linux /work/actor身份；不能关闭原有workspace/source seal检查来迁就路径变化。旧TaskReceiver在宿主用Path.resolve核对工作区，不能原样冒充跨平台身份映射已支持。
- Linux协议中没有Python任务运行时准入。本轮WSL提供系统shell；上轮容器Python3.11.16不自动成为本层已有工具。T3迁移任务的解释器、SQLite和验收条件仍需同臂一致、单独核对。
- 准入源码与运行文件还需在未来正式登记前整体封印。本轮as-run快照是运行后保存，不伪称已做付费研究预注册。

因此private_boundary_qualified、paid_dispatch_admitted仍为false；研究累计已知5080960 Token/141回执和全部未知不变。不能从这次基础设施成功推出WSC更省、更快或更正确。

## 下一步

在此旁路上建立明确的宿主/客体工作区映射并接通正常WSC来源访问，保持来源身份、cut、epoch和失效错误。随后验证任务运行时及受控提供方连接。只有这些条件通过，才从现有预算登记具有独立信息的最小新对照；不重开旧T1、旧T3账本或增加原上限。

复用官方运行文件与已有WSL可减少对Docker后台和历史Windows ACL状态的依赖；本轮仅证明了接入可行性，不计成压缩算法性能收益。后续不继续围绕Windowsdeny参数补丁，也不为当前低命中去噪新增模型组。

## 证据与复现

准备及边界原语：D:/agent-task-runs/wsc-linux-runtime-admission-20261029-v1。

真实协议：D:/agent-task-runs/wsc-linux-native-protocol-20261029-v1。

外层原生及私有文件：D:/agent-task-runs/wsc-linux-native-envelope-20261029-v1和v2；v2 registration.json保存宿主31文件SHA，private-read-probe.json保存64路径及真实返回，methods-issued.json保存请求方法，rollout.jsonl保存实际合成历史，cleanup.json保存WSL终止结果。

源：validation/provision_linux_codex_runtime.py、validation/qualify_linux_native_protocol.py、experiments/native_linux_envelope.py。--owned-wsl-distribution只适用于调用方已确认独占、初始停止的发行版；清理会终止该发行版，不能用于用户已有活跃Docker/WSL工作的环境。

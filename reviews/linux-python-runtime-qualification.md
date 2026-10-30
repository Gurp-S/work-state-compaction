# 隔离 Linux Python 任务运行时

2026-10-30。补齐真实模型闭环前的任务执行条件；0 模型调用，没有重跑 B/C。

## 运行时与边界

现有 python-3.11.9-stdlib 是 Windows 包，不能用于 Linux 原生工具。选用 [Astral 上游固定发布 20261026](https://github.com/astral-sh/python-build-standalone/releases/tag/20261026) 的 CPython 3.11.18 x86_64 Linux musl 精简包。资产元数据、包大小与 SHA-256 核对后才解包。

包 29417739 字节，SHA-256 `77a7cc357d060f31208d2c61bf845961ba55e23e92b85eb508d09421608e0337`。保留上游解释器及 lib 常规文件 1831 个、77388838 字节，包括原许可证；不改二进制字节。不提取无关 share/开发头文件/其他启动器，3 个符号链接别名未创建。明确使用 /opt/python/bin/python3.11。没有系统安装或改用户全局配置。

位置：D:/agent-task-runs/wsc-tools/python-3.11.18-20261026-linux-musl。未来配对实验两臂须使用相同清单；不能与旧 Windows 条件混作严格算法对照。

新增 experiments/native_linux_python.py 只在原闭集挂载策略后增加只读 /opt/python 与 PATH。保留 --unshare-all、独立 UID 65534、私有 /proc、无宿主盘暴露，不使用 --share-net。不把全局 WSL 网络或 Docker socket 暴露给任务。五项挂载构造检查通过：原策略前缀不变、没有共享网络、只读 Python、错误根拒绝、工作区重叠拒绝。

## 实际执行结果

使用未修改的同版 Linux Codex 0.165.0-alpha.1.2，经 initialize / command/exec 执行 Python。没有 turn/start、thread/compact/start 或模型请求。

真实命令中的 3 项程序检查全部通过：

- 工作区 SQLite 数据库事务回滚、旧值保留、迁移增加字段及默认值断言。
- UTF-8 / JSON 精确值与非法字节拒绝、SHA-256 基本可用性。
- 宿主真实存在的私有 canary 及 /proc/1/root 变体不可读；工作区符号链接指向该 canary 仍不可读；/opt/python 写入失败。

观测 Python 3.11.18、SQLite 3.53.1、UID 65534。命令前后逐文件核对运行时清单一致。不是通用安全证明，也没有验证网络提供方或模型补证行为。

## 失败保留与复用

下载首段达到自设 90 秒上限，保存 20971520 字节与摘要。随后显式 Range 续传，仅接受正确 206 / Content-Range，最终全包 hash 核对；没有重下前段。解包首轮发现 Linux Eterm/eterm 在 Windows 大小写不敏感文件系统冲突。保留错误、碰撞原名、修改前提取器；提取范围收紧到实际所需解释器/lib，不覆盖文件。

原生执行 v1 中解释器已经运行，但 command/exec 默认只读，建库和建符号链接失败。保留原命令、输出、执行源码。v2 显式限定 workspaceWrite、writableRoots=[/work/actor]、networkAccess=false，3 项全过；外层隔离不变。环境修正不计 WSC 算法收益。

下载/提取证据：D:/agent-task-runs/wsc-linux-python-provision-20261030-v1。
真实原生失败/通过：D:/agent-task-runs/wsc-linux-python-native-20261030-v1、v2。
每次 WSL 开始前确认 Stopped、由本轮独占启动，结束 terminate 成功；没有残留后台实验。

## 下一步

真实任务运行时已具备；受控提供方连接尚缺。接下来实现限定通道和预算的通信旁路，凭据留在协调器，保留当前文件与网络隔离；先做零模型请求/响应连通检查，再登记最小真实模型概览及回查任务。当前没有真实模型恢复、实际 Token 净收益、任务正确率或新 B/C 结论。

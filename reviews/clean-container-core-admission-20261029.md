# 干净容器中的 WSC 核心准入：无模型通过，原生 Codex 尚未接入

2026-10-29。接续两次 Windows 原生实际拒读失败，本次改查已有隔离环境，不重跑旧 T1/T3，不调用模型，不提高研究上限。

## 结果

本地 Docker 后台启动成功，使用现有 python:3.11-slim 的完整镜像 ID 固定运行，不 pull、不 build。读取旧 WSC 镜像仅确认 Python 可用，未发现 Node 或 Linux Codex；未执行旧镜像的应用入口或模型代码。没有把旧镜像的存在当作历史隔离测试已经通过。

当前 WSC 的62份 Python 源码逐份 SHA 绑定。实际创建并检查的新容器只有一个 bind mount：wsc/src → /opt/wsc-src，且只读。工作数据全部在16MiB的临时 /work 中；没有挂载仓库、评分器、报告、旧答案、宿主会话或Docker socket。

运行限制：非管理员UID65534、只读根文件系统、cap-drop ALL、no-new-privileges、无网络、64进程、256MiB内存上限、1 CPU。实际仅有lo网络接口，指定宿主路径和Docker socket均不存在，写源码挂载失败。

WSC真实核心在该环境完成：

- 导入2条固定合成消息，capture、prepare、stage和package。
- 强制控制消息与原值一致，未被热选的观察原文可从导出的冷证据文件精确读取。
- 重开SQLite后source digest和package digest一致，cursor仍为0；没有把导出当作安装成功，没有伪造原生宿主回执。
- 源码前后SHA一致，容器按实际ID删除成功。

这里验证的是核心执行、导出和冷文件往返，不是模型使用WSCSource工具后的补证能力，更不是任务正确率或新压缩收益。

## 仍缺的条件

容器Python为3.11.16、SQLite3.46.1，旧原生实验运行时为Python3.11.9；宿主也由Windows变为Linux。这些必须在新登记中固定，不将后续数字与旧实验混成严格单变量比较。

Linux原生Codex尚未接入、其版本和启动消息未绑定，真实压缩与模型恢复未验证。当前network=none不允许提供方调用；未来只能在明确的网络/凭据边界下验证正常模型连接，不能因本次无网络检查通过就宣称联网后同样隔离。无论原生还是WSC，两臂必须在相同新环境运行；旧结果继续作为历史参照，不能假装与新环境完全一致。

下一步核对可复用的Linux原生运行方式及版本，先做无模型初始化、实际私有访问检查和WSC恢复接入；这些条件通过后，才按原研究预算登记有独立信息的新最小控制。没有为迁移环境授权无限重跑旧组。

## 资源与清理

启动已有Docker引擎时，已有Neo4j容器自动恢复；本任务未改其数据或配置。检查结束后执行已有Docker Desktop的正常停止操作成功，将引擎还原到本轮开始的停止状态，没有为这次资格保留后台容器。没有下载镜像，没有把镜像或运行时打包进WSC版本。

研究已知5080960 Token / 141响应及所有未知保持不变，本轮模型请求0。该数字是已汇总实验账本下界，不是本聊天Goal用量或完整历史费用。

## 证据

D:/agent-task-runs/wsc-clean-container-admission-20261029-v1：registration.json固定镜像ID、源码SHA、创建参数和smoke SHA；container-boundary.json来自实际docker inspect；execution.json保存stdout/stderr；results.json标明native_codex_qualified=false；cleanup.json保存确切容器ID及删除结果。

复现入口为wsc/validation/qualify_clean_container_wsc.py，--out使用新目录。只使用已有本地镜像，输出目录独占创建；本次仅运行一次该核心准入。初始化环境镜像探针与正式核心准入不是独立任务重复样本，不据此计算统计显著性。

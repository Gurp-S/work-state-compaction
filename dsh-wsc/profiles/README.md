# 安装示例

- `desktop.cordis.patch.yml`：一个完整的 desktop profile 示例（provider、模型、
  预设花名册与 WSC 接线）。内部地址与模型名需要按你的部署替换。
- `desktop.package.json`：profile 包描述，`@xeyo/dsh-wsc` 用 `link:` 指向本仓库。
- `default.cordis.patch.yml`：最小接线，只开 `mode: active`，其余取 v3r 默认值。

压缩后端在 `cordis` preset 里替换 `compaction-basic`；`wsc-config` 是宿主面策略
服务，引擎在 `wsc-engine` 里读取。`mode: off` / `shadow` 只做记录、不改写上下文。

# 文件与资源管理应用

遵循 ../../COMMON.md。交付有列表/网格、目录、上传队列、详情和版本历史、回收站与分享管理的资源中心。本地文件内容由服务端持久化。公开小样本上传以 JSON base64 传输，前端文件选择器读取真实文件；不能用文件名或大小代替内容校验。

## S1 上传与下载

`POST /api/uploads {name,folder,size,sha256}` 创建上传，返回 id、offset:0。folder 为以 / 开始的逻辑目录，name 为不含路径分隔符或 .. 的单个文件名。`PATCH /api/uploads/{id} {offset,data_b64}` 写入块，返回当前 offset。`POST /api/uploads/{id}/complete {}` 校验总长度与 SHA256，成功201返回文件对象 id/name/folder/size/sha256/version（初始1）。错误内容422且不发布文件。`GET /api/files/{id}` 为元信息；`GET /api/files/{id}/content?version=N` 返回 data_b64；省略version为当前版本。浏览器下载还原原字节。

## S2 中断续传与身份

`GET /api/uploads/{id}` 返回 name/size/sha256/offset/state，重启后可续传。相同 offset 和相同字节重复块幂等；相同 offset 不同字节409，跳过 offset409。已完成上传再次 complete 返回200同一文件，不重复创建。上传信息绑定原身份，不能把同名新文件接到旧内容后面。页面明确显示暂停、重试、失败与完成状态。

## S3 目录、标签与搜索

`PATCH /api/files/{id} {version,name或folder或tags}` 修改元信息。`GET /api/files?folder=...&tag=...&q=...&limit=...&cursor=...` 返回 items/next_cursor；q为名称包含，folder精确，tag包含，排序稳定。任何 .. 路径分量、反斜杠或非法base64返回400，不能越过 data 根目录。目录和标签是持久化逻辑对象，不让原始路径控制物理文件位置。

## S4 版本与并发

`POST /api/files/{id}/versions {version,data_b64,sha256}` 原子替换当前内容，成功201增加version，旧内容仍可下载。PATCH 同版本竞争只有一个成功。历史内容不因重命名变化。新增内容hash不符422且当前文件不变；UI展示版本、hash与恢复/下载入口。

## S5 删除与恢复

`DELETE /api/files/{id}?version=N` 将文件移到回收站，增加version并返回对象。普通GET与普通PATCH均404；`GET /api/trash` 可见，`POST /api/files/{id}/restore {version}` 恢复并增加version。删除前迟到的旧版本写入不能复活文件；恢复也不使旧写请求重新有效。回收站显示删除状态并确认永久删除：`DELETE /api/trash/{id}?version=N`。永久删除后恢复404。

## S6 角色与分享撤销

`POST /api/shares {file_id}` 返回 token，`GET /api/shared/{token}` 无登录返回当前可见文件的 data_b64。`DELETE /api/shares/{token}` 撤销，之后访问404，重启也不能恢复。删除文件即使尚未撤销分享也不再可读；恢复文件不自动恢复原分享。viewer不能上传/删除/发分享；tenant-b不能读取tenant-a内容。

## S7 大列表与清理

1000个元信息对象仍可分页、搜索、键盘操作，上传进度不会阻塞列表。`POST /api/maintenance/gc {}` 仅admin可用，回收不再被当前、历史版本或活跃上传引用的内容；引用中的字节保持。验收对有效历史版本重新核对内容；不靠清掉历史来降低内存。

## S8 重启与既有数据

起点 `files.sqlite3` user_version=1、records(id TEXT PRIMARY KEY,payload TEXT NOT NULL) 含 welcome：name README.txt、folder /、content_b64 为 UTF8 "Welcome\n"、tags=[]。首次升级后可用 `/api/files/welcome/content` 下载原字节。既有 id 不变，迁移幂等。重启恢复未完成上传、旧内容版本、删除和撤销事实。完整交付不等于接口存在。

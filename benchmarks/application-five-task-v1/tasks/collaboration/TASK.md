# 项目与工单协作应用

遵循 ../../COMMON.md。从 TeamFlow 单工作区原型演进为真正可协作的应用。UI 包含项目导航、看板与列表、工单详情、评论、成员、批量操作和审计视图。使用稳定身份关联，不把标题当主键。

## S1 项目和工单

实现项目创建和切换、工单创建/查看/编辑。`POST /api/projects {name}`；`POST /api/issues {project_id,title}`；`GET /api/issues/{id}`。工单含 id、project_id、title、status、version，初始 todo/1。标题 1-200 字符；项目不存在返回404。`PATCH /api/issues/{id}` 接受 version 和要修改的 title/status。`GET /api/issues?project_id=...` 返回该项目工单。

## S2 组织与成员

落实共同合同的租户隔离、角色和权限变更。用户不能靠猜 id 跨组织读取或修改。成员降为 viewer 后已打开页面的旧操作也被服务端拒绝；界面显示失败并保留可核对的原内容。

## S3 流转与评论

`PATCH /api/projects/{id}/workflow {states:[...],edges:[[from,to],...]}` 设置该项目流转；默认 todo→doing→done。非法流转409；规则更新不改写已有工单的事实状态，不允许删除仍有工单使用的状态。`POST /api/issues/{id}/comments {text}` 和 GET 同路径；评论返回 id/text/author，作者来自当前身份。历史评论不可因规则更新丢失。页面可清楚查看可执行流转。

## S4 并发编辑

PATCH 要求当前 version；同时提交同一版本只有一个成功，另一项409，返回当前版本信息。UI 保留用户未提交内容、展示冲突并允许重新载入，不能静默覆盖。先前的角色与流转校验继续生效。

## S5 批量、撤销与审计

`POST /api/batches {operations:[{id,version,changes:{title或status}}]}` 原子提交，任何一个失败则全部不变；成功返回 id。`POST /api/batches/{id}/undo {}` 原子恢复批次涉及字段，只有这些工单仍为批次刚产生的版本才允许；否则409且全部不变。撤销也增加版本，不回退版本号。`GET /api/audit` 返回有 actor、action、resource_id 的记录；成功写入与对应审计同事务，拒绝项不能伪装为成功。提供批量选择、预览和撤销结果。

## S6 旧数据迁移

首次起点含 `teamflow.sqlite3` user_version=1，legacy_projects(id,name)、legacy_issues(id,project_id,title,status)。既有项目 welcome 和工单7（原样标题、todo）迁到 tenant-a，工单 id 对外为"7"、version=1；迁移原子且幂等，重复启动不会重复或重置版本。新数据与旧数据一起工作。迁移后按 S3 配置流转仍能编辑旧工单。

## S7 搜索与导出

`GET /api/issues` 支持 project_id、q（标题包含，Unicode）、status、limit（1-100）、cursor；返回 items、next_cursor，稳定 id 升序分页且无重复漏项。`GET /api/issues/export` 同筛选但不分页，返回 items，范围和字段与服务端真实数据一致。筛选后的批量选择只操作明确选择的 id。键盘能完成创建、搜索、查看与编辑。

## S8 持久化与交付

服务重启后工单、评论、规则、权限、批次和审计保留。测试冲突后重启、迁移后再启动和权限降级后重试。交付完整界面、运行说明与证据；前期检查不能替代最终源码验收。

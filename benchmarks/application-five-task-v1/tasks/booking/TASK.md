# 预约与通知管理应用

遵循 ../../COMMON.md。交付资源列表、周/日历、可用时段、预约详情、改期取消、重复预约和通知状态的完整应用。不调用真实邮件服务；通知通过本地可检查接收端模拟。所有承诺时间保存为绝对时刻，页面显示明确时区。

## S1 资源与预约

`POST /api/resources {name,timezone}` 返回id/version（1）；至少支持UTC和Asia/Shanghai。`POST /api/bookings {resource_id,start,end,idempotency_key}` 返回201含id、resource_id、start/end（带offset的ISO8601）、state=confirmed、version=1。`GET /api/bookings/{id}`；列表 `GET /api/bookings?resource_id=...` 返回items。UI能从资源日历创建预约并打开详情。

## S2 时间与冲突

预约区间为[start,end)，端点相接不冲突，重叠409，end<=start或缺少时区400。`PATCH /api/resources/{id} {version,timezone}` 只改变显示/以后输入默认时区，不移动已承诺绝对时刻。`PATCH /api/bookings/{id} {version,start,end}` 改期，检查冲突后原子替换；失败保留原时段。不同offset表示同一时刻时按绝对时间判断。夏令时歧义输入需明确offset，不接受无offset推断。

## S3 并发与幂等

两个请求同时争抢相同时段至多一个201。相同身份、idempotency_key及payload重放200同id；不同payload409，重启后也有效。并发改期要求version，失败不丢失原预约。界面重复点击或重试不能生成重复记录。

## S4 重复预约

`POST /api/series {resource_id,starts:[带offset时间...],duration_minutes,idempotency_key}` 一次生成有限重复预约，返回id/items，各项有series_id/index。UI支持按周生成可预览的明确日期（至少UTC与上海）；提交前展示全部时间。全部实例原子校验，任一冲突则409且全部不创建。`POST /api/series/{id}/cancel {from_index}` 取消该索引起的未来项，保留较早项，不移动历史承诺。用户修改重复规则时明确作用范围，不把一次修改变成全部历史重写。

## S5 通知队列

创建/改期产生对应当前预约版本的提醒，due_at为开始前1小时。`POST /api/notifications/dispatch {now:带offset时间}` 执行到期队列，返回结果；同消息重复调度不重复投递。`GET /api/notifications/deliveries` 返回有message_id/booking_id/booking_version的已投递items。仅用于本地演示的 `POST /api/notifications/test-sink {fail_next:1}` 让下一次尝试失败；失败留待重试，成功接收按message_id去重。清楚显示未发送/重试/已发送，不能把排队当已送达。

## S6 取消、改期与授权失效

`POST /api/bookings/{id}/cancel {version}` 增加version、state=cancelled并释放时段。取消/改期后的旧版本通知不可再发送；取消后重启也不复活。成员权限下降使旧编辑页面操作403；跨租户不可看预约或投递记录。已取消预约再次取消返回当前状态，不新增通知。

## S7 导入与可访问性

`POST /api/bookings/import {rows:[{resource_id,start,end,idempotency_key},...]}` 原子导入，返回items；任一冲突或非法输入全部失败。支持1000条历史列表分页（limit/cursor）和日期定位；键盘可创建、改期、取消，窄屏可读日程列表。通知错误可查看，不靠颜色区分。

## S8 恢复与旧数据

起点 booking.sqlite3 user_version=1、records(id,payload) 含welcome：resource_id=room-a、start=2026-10-22T02:00:00Z、end=2026-10-22T03:00:00Z、state=confirmed；升级时创建或保留room-a(UTC)。既有预约可读取，id不变。重启保持预约、已取消状态、幂等键、未处理通知和已投递去重。交付完整应用、迁移与恢复说明、最终功能及视觉证据。

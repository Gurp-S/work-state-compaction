# 独立 WSC 本地续接：当前交接

更新：2026-10-27。当前代理直接完成，不使用子代理。长期目标未达成。用户确认额度恢复，明确采用实际实验运行时间累计、额度等待不计；旧消耗、失败、未知及原上限不变。以下历史段落不覆盖本节。

## 最新：三条独立C1/C2完整链完成，C6/6、B3/6，平均仍贵25.57%

[三完整链报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-c1-three-full-chains.md)。复用v1.31新C R01及历史三B，只补两条完整C1/C2/QA，并行2worker/共享ledger；不再共享C1冒充独立全链，不加新输入格式。三C146346/180767/149866平均158993，6/6；B145645/135148/99045平均126612.7，3/6。比旧C平均188466.7少15.64%，但比B多25.57%，非超越/省时。C1新均62934.3，旧89442少29.64%；首input61299/61320/61322较稳定。

平均阶段C56.885秒、B30.162；C1自身新均18.979>旧16.828，不称提速。R01完整墙钟unknown保留，R02/R03 101.671/87.453秒。C2同三次读取但R02多一响应，input多31248、缓存input多30720、output少24，阶段都27.9；Token差不等价计算/时间/金额差。既有同案例规律位置可推别名，实际恢复仍有原文确认，不称检索泛化。

全部三C实际请求/schema/641源等价审计，C2目标nonce不在输入/schema，实际工具返回与评分2/2、回执/进程闭合，原DB不变。新9回执/330633Token逐臂与全局对账。审计复用单臂/恢复字段假设导致的两个KeyError补记保留，修为--arm及单链阶段求和、optional恢复标记，0模型重跑。另修LateCell异常对账硬编码R01的guard，按rep标未知并全局冻结；前后测试旧peer可准入/新拒绝，5定向过。执行两进程加载旧代码，正常轨迹未触该分支，原执行模块保留；不拿异常guard修复冒充模型收益。

证据wsc-c1-columns-repeats-20261027-v1与wsc-c1-three-chain-report-20261027-v1(JSON/CSV)。最新封套repeats/next-admission-envelope.json：18091795/280/11143秒，新增330633/9、101.671扣ceil102，保守1040000/24扣留非实际/未知上界。全三C476979/13含复用146346/4，不重复计费，维护/审计unknown与旧失败保留。v1.32只存增量/小证据，不复制DB/cold树。

下一步结束此案例重跑，保留C1候选。转向C2整目录常驻/往返重复输入，先离线设计短绑定入口＋完整事实恢复，证明源/权限/失效/引用不弱化并披露资源差异，不新增语义排名，不让引擎决定保留。通过准入再小额资格及状态覆盖/失效/依赖扩展，长期目标active。

## 历史：C1新表示完整链2/2、146346Token，成本下降但尚未超原生

[C1事件列报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-c1-event-columns-qualified.md)。预算独立整表查询的额外请求成本大、piggyback有16KiB限制，先不加工具。发现首轮C1事件227280B/公开原文111060B，大量重复元数据。新native_event_columns保序同构列、原span/ref/文本/字段完整保留，异构/无收益回退，默认关闭；C1用event_columns+metadata_columns，C2仍稳定cold_event_table，未用上一轮慢的C2列式。

0模型旧C1请求/草稿还原编译等价，246019→150594B（实际150591）；新C1 input87949→61299（少30.3%）、总89442→63465（少29.04%）。真实完整链C1 63465/1、C2 64061/2、QA18820/1，合146346/4、2/2；原稳定行表177645少17.62%，比既有三组B平均126612.7仍高15.59%。C1阶段20.703秒比旧16.828慢，整链阶段56.641秒，但C2选择/服务波动，单次不证稳定提速。实际录制区间下限87.072140秒，完整外层墙钟unknown，不冒称精确加速。

收尾误将boot.close()字典传timing.call导致TypeError exit1；cell模型/cleanup已全部落盘。execution-failure保留，executed脚本逆向重建与登记SHA完全匹配；0模型按4唯一回执/closed logs/bootstrap清理恢复ledger，started/seconds派生于span并标注不是旧内存原账。新settle_bootstrap用span关闭且finally保存dispatch-ledger，清理失败仍保留unknown/inflight，未模型重跑。23定向/18子用例过。

独立audit实际C2无nonce、原s540工具回执与评分2/2、全进程清理；C1实际请求绑定及解码后与旧同（仅manifest locators、fresh source_digest/source id规范化），641源除新id外内容严格同，schema同，原DB不变。

证据wsc-c1-columns-admission/qualification-20261027-v1、wsc-budget-delivery-audit-20261027-v1。最新封套qualification/next-admission-envelope.json：19131795/304/11245秒；新增实际146346/4，保守520000/12扣留非实际或未知上界；准入.153扣ceil1、录制下限87.072扣ceil88，其他unknown/旧失败保留。v1.31增量不复制DB/cold树。

下一步冻结C1新列式＋稳定C2，复用新已完成C及历史B三组，只补两条独立完整C1/C2/QA（不共享单次C1冒充三重复），检查成本/质量分布再考虑推广及状态覆盖/失效案例。长期目标active，未证总体超原生。

## 历史：投影预算事实错误已旁路修复，0模型；重复read并非无信息

[预算接口报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-projected-budget-interface.md)。旧facts/admit用未投影字节，实际prepare用native_source_refs_v1，span文案又覆盖为完整payload。新独立projected_selection_facts＋frontier(projection_facts=True)显式计算最终存储投影，默认旧路径保留，最终硬检查/权限/发布状态机不改。新schema保留至span前端，不让表述覆盖存储契约。

真实A/B：普通观察旧200148B/新与实际143B；控制空视图旧190/实际234B；大型显式control旧200338B误拒1000预算，新377B与真实prepare均过。opaque必留/未知mode仍拒，预算减一新预检与prepare均拒，17定向通过。真实晚位全643消息源，空视图仅1526→1570差44B，不能解释上一轮长推理或声称提速。

实际find(s540)只有0..186片段，read补到227、额外41字符和complete/fullhash证明；不能引擎按已见nonce自动删除这个read。没有证据证明模型在手工算预算，不凭隐藏思考猜因果。本轮0模型；源DB不变。证据wsc-projected-budget-audit-20261027-v1，开发测试路径/别名断言失误补记保留，非模型实验失败。

最新封套该目录next-admission-envelope.json：19651795/316/11334秒；已知.084468扣ceil1，测试/导入/维护unknown及全部旧失败/用量保留。v1.30增量不复制大DB/cold树。

下一步离线设计预算事实按需查询：原事实完整可获取、源/权限绑定、计量对齐，先验证输入收益再小额模型资格，不重做三组、不推广未提速列式。长期目标active。

## 历史：列式候选首请求Token下降48%，总费只少3.7%、耗时增加，默认不推广

[列式资格报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-metadata-columns-qualified.md)。新独立native_metadata_columns只对既有旧事件行/预算行作严格类型等值段、字典、整数/前缀整数列与单字段包装，完整hash绑定/还原；不删字段/文本/来源，不决定重要性，不改输出schema。generate(metadata_columns=True)默认关闭，真实入口需新增准入hash/源DB匹配，policy另记metadata_columns_v1。

三旧接受请求0模型完整还原和旧草稿编译等价；请求约55479→11246、55471→11238字节，事件rows33535→456、预算14680→3526。22定向/18子用例通过，非全项目。新实际请求11251字节（路径差异），首响应input30214→15697Token（少48%）；但新5工具/3选材响应，选材输出10008其中reason9607，旧7243/6858。C2+QA实际84923/4、2/2、109.218秒，原88203/3、2/2、95.406秒：费少3.7%、时间多14.5%，未证明提速。含共享C1逻辑174365/5，原177645/4，少1.85%。不能由单次推断格式导致额外思考。

独立column-run-audit证实新输入还原除manifest locator外与旧同、schema同、643源对象同、原文工具输出与4唯一回执精确对账、cleanup确认，原DB不变。无新B/无重复三组/无额外裁判。frontier2.183、发布4.787、evidence.122秒，本地3次编译等价.288秒；模型pipeline86.292不是编码计算耗时。冷目录DB-only分叉仍重建，未跳同步/校验或共享可变文件。

证据wsc-metadata-columns-admission-20261027-v1与qualification-20261027-v1；后者最新封套19651795/316/11335秒，新增实际84923/4，保守320000/8扣留非实际或未知上界。零模型已知.324扣ceil1，维护/审计/测试unknown与旧失败/花费保留。v1.29增量不复制DB/cold树。

下一步不推广默认、不重复大批评测。0模型复盘实际源调用与预算接口，检查能否把确定性资源核算留给引擎，减少模型重复验证且保留可恢复信息/源绑定；不把字节下降当最终性能成功。长期目标active。

## 历史：晚位三组完成，C6/6、B3/6，平均完整链Token多48.85%

[三组报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-late-three-pairs.md)。同晚位案例/两问题，三组U6/6、B3/6（每次当前正确、旧nonce未恢复）、C6/6。三个C共享旧C1，R01历史结果，R02/R03新C2＋后测；不是三独立完整选材链/三个任务。B各自真实两压缩，所有6次确认，不解析摘要。默认模型与输入协议不变，新C仅已验函数绑定优化/主机计时。

完整逻辑链平均B126612.7、C188466.7 Token（每C均加回共享C1 89442），C多48.85%，不省；阶段平均B30.162、C79.411秒，不作历史/新时刻因果速度结论。R02/R03 C实际68.953/76.906秒，不含C1；冷发布4.738/5.306秒，局部热微基准收益不外推。新C请求均55471字节，独立审计除manifest locator外同旧请求，schema相同；R02一次find/2选材响应，R03四工具/3选材响应，模型策略有波动。

新两组并行3worker、两组顺序、相反提交顺序，新增563950/17、145.938秒。全部原DB/源不变、回执精确对账、cleanup确认。源工具审计初失败是R03模型双重JSON编码，原括号扫描漏读；新增validation/structured_tool_outputs有界严格JSON旁路，只审计不改评分/模型输入。真实旧/新审计A/B R02 1→1、R03 0→4精确输出匹配；3正反例过。旧失败补记保留，时间unknown，0模型重跑。报告JSON/CSV/input分项在wsc-late-three-pair-report-20261027-v1，原始在wsc-late-remaining-pairs-20261027-v1。

最新封套后者next-admission-envelope.json：19971795/324/11446秒；1920000/48保守扣留非实际563950/17或未知上界。维护/审计/测试unknown及旧失败保留，未重复扣C1。v1.28只存增量与小证据，不复制DB/cold树。

下一步不重跑本案例，0模型调查events34599＋selection_facts16177占请求约91.5%及冷制品重建数秒的结构性成本，先完整还原/源绑定/权限/持久化等价证明，再决定小额资格。不能由本例推断状态覆盖/关系/50次压缩已正确；长期目标active。

## 历史：晚位第一组对照完成，U2/2、B1/2、C2/2

[第一组报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-late-first-pair.md)。补齐同晚位320构建案例的真实原生B（两次压缩各有绑定回执/持久边界/terminal证明）及未压缩U，复用行表资格C，不重付C1/C2。U2/2、B1/2（旧nonce答不可获得、当前321正确）、C2/2。这是历史C/前瞻B混合系统观察，一组不是三重复，不解析加密摘要；不能推断摘要包含或丢失哪些内容。

完整逻辑链B145645/5、C177645/4（含共同旧C1），C多32000约22%，不省Token。B阶段38.657/实际46.719秒；U62038/1、阶段6.938/实际15.000秒。C历史阶段92.218，不与B作当前配对墙钟结论；上一轮95.406实际是C2-only。当前没有新优化C整轮加速证明。

新独立late_native_counterpart入口原bootstrap分叉，前缀/全文与原parent按既有传输标准化校验，actor/executable/问题/后测预算相同，两个worker并行B/U。0模型准入4.562秒通过，实际新增207683/6、46.719秒；独立确定性audit重算分数、两次压缩证明、6唯一回执、账本、源不变及全部cleanup。重复audit既有结果相同则不覆写。旧失败/unknown保留，无额外LLM裁判。

证据D:/agent-task-runs/wsc-late-native-admission-20261027-v1与wsc-late-native-counterpart-20261027-v1；后者next-admission-envelope.json最新21891795/372/11592秒。640000/16是保守扣留非实际207683/6或未知上界；维护未完整计时unknown。v1.27仅执行器/报告/小证据增量，父v1.26，不复制DB和cold树。

按用户第一组结束先报告，本轮不扩大派发。下一步后两组，保持输入协议，使用已验证性能旁路及计时，复用共同C1并明确“固定C1后C2条件重复”而非三独立完整选材链。固定并发/冷热初始环境、记录实际与逻辑全链成本；原生B仍真实两次压缩。长期目标active，未证明总体超越原生。

## 历史：保持模型与输入的耗时优化，先优化再三配对

[耗时归因与性能报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-latency-attribution-and-performance.md)。复用后整轮110.750→95.406秒，省15.344秒；先前31.8%变慢仅指C2+QA。C2多24.203秒主要在非工具服务区间（多24.176），工具仅.011→.030秒；不把服务区间冒作纯模型计算。复用只带DB/草稿，新cold目录重新物化，不能忽略冷热差异。

新增默认关闭的主机计时native_latency与BoundWindowsIO，只缓存Win32函数绑定，不缓存文件/权限/hash或省检查。5交替稳态发布中位.417268→.327726秒（21.5%局部），包与1294对象逐字节同；不是整轮21.5%收益。服务准入可复用实际选择器、减少一个一次性进程，额度检查仍在模型派发前，模型可见items相同。39过/1本机symlink跳过/6子用例，非全项目。本轮0模型调用，默认原路径保留；冷回放、微基准与实际模型轮不能混比。

证据wsc-latency-analysis、wsc-external-latency-replay、wsc-bound-io-profile-v1/v2、wsc-publication-bound-io-profile-v1/v2、wsc-selector-readiness-reuse（均20261027）。最新封套latency-analysis/next-admission-envelope.json；旧unknown/失败/花费保留，维护/预热等未完整计时仍unknown。v1.26为v1.25增量。

下一步固定协议做晚位三次B/C，明确冷热初始制品、并发与顺序，记录总墙钟及组件耗时，复用兼容已完成单元并标明历史属性，不再增加输入格式；真实native压缩，不做额外LLM评分。

## 历史：旧事件可逆行表实际2/2，后续Token少31.3%，但阶段更慢

[行表报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-event-table-qualified.md)。独立native_event_table.py/可选generate(cold_event_table=True)，old text_in_frontier is False共同字段defaults/具名列/原event_index，不删字段/正文/角色/来源，不语义筛选；异构/无收益原样通过。默认关闭，C-only --cold-event-table与新策略/event_rows_v1；schema先生成所以输出schema不变。严格哈希/类型/索引恢复，false0null/missing不混。

真实旧请求+草稿0模型还原/编译等价通过。准入v1/v2脚本分别忘恢复原text、预算表原source身份而失败，均0模型，原目录保留；修正审计接口层后v3过。36定向/6子用例过（6文件），非全项目。

复用晚位资格C1 89442，不再运行。新C2选材69187/2（旧109456/2），查询19016/1（旧19022/1），合88203/3（旧128478），少31.3%；含复用C1完整链路177645 vs217920少18.5%。请求145655→55479B；首次输入51930→30214；仍2/2。新读s540/s643/s642三次正常来源，旧一次find；模型输出更多、C2+查询阶段57.219→75.39秒，慢31.8%。不宣称更快/金额/任意任务质量保证，不把所有总量差都归因静态编码。

新source-tool-audit核对3工具实收原文/哈希；table-run-audit解码后请求除冷清单path/sha定位外全等、schema全等、643source对象文件相同，原DBhash未变。源码源中M=0准入，旧C2信息不经M目录泄漏；新线程只给C1 previous状态，旧views/用量保留但未注入。实际新模型policy单次资格不是正式3对或B优势。

证据wsc-event-table-admission-20261027-v1/v2/v3、wsc-event-table-qualification-20261027-v1（candidate全日志/新绑定/两个audit/comparison）。最新后者next-time-reconciled-envelope.json：22531795/388/11697秒；成功0模型准入.078另扣ceil1；失败准入hash/精确时间unknown，failure.json为观察错误后补记非虚构自动回执。新增实际88203，不是含C1的177645，保守320k扣留非实际费或未知上界，旧unknown/维护unknown保留。版本v1.25保存代码/报告/小证据，不复制DB/cold树。

下一步固定这版协议做晚位三次B/C，复用已完成单元并明确历史已知属性，补缺失C/B/未压缩基线；必须真实native compact不假摘要。完成前不再叠加输入新格式。之后再其他案例/多轮；长期goal active。

## 历史：晚位旧证据真实C续接2/2；下一步压缩重复元数据，不重做C1

[资格报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-late-recovery-qualification.md)。新seed20261028/320构建，641旧来源目标build270在s540，后50构建。新独立late_recovery_case+LateCell复用核心真实两选择/导入，最初没预告审计目标；新用户审计在C1结束后才入历史。0模型准入过28.734秒；实际C1模型89442/1，C2选择109456/2，后测19022/1，共217920/4，2/2。C2真实请求/schema均无目标nonce，模型一次find(build270)收到旧s540原回执与新s643请求，正确答旧nonce/current321。独立audit核对生成绑定、原文hash和native实际工具输出、回执/评分/清理。

本例不是B对比或三重复，未native compact；不fake原生摘要。两个selector同minimal+compactwire+budget_results+snapshot_literal，第二个全新不继承原prefix；答题正常WSC包兄弟隔离。选材前无oracle文件。0模型准入的空选只是接口检查，真实C1/C2均模型决定。30定向/6子用例（6文件）通过，所有owner清理确认。

实际C2请求145655B+schema5873B，events124776B占请求85.7%，旧641事件重复kind/不可见/null/空span/frontier=false，sourcefacts16177B。C2输入51930与52935（缓存51712），非免费恢复。离线仅将旧元数据共同字段defaults/其余列带原位置成表，全字段严格还原，候选request55421B（-62%）。input-audit明确production_codec_implemented=false，未证明新模型Token/质量收益；不把byte当Token，不语义筛选。

证据wsc-late-recovery-admission-20261027-v1和wsc-late-recovery-qualification-20261027-v1（audit/input-audit/feasibility及所有raw）。最新封套后者next-admission-envelope.json：22851795/396/11794秒。实际已知217920，保守扣520k分配非实际/未知上界，旧研究unknown保留，维护未完整计时。v1.24保存新case/执行器/审计/报告/小证据，不复制DB/cold树。

下一步通用可逆冷元数据行表：类型/缺失/false0严格、旧草稿/请求还原与编译等价后，仅复用本次C1做新C2小额质量检查。通过再晚位三次B/C（真实B/未压缩同题基线/统一预算），不重做89442Token C1，不直接扩75格。此case有规律receipt/log排列，已观察实际find但不称唯一恢复路线；正式扩展须说明。长期goal active。

## 历史：大历史后部证据可达性已复现并做可选快照检索，0模型

[本轮报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-late-source-reachability.md)。默认find把每条不匹配日志也读DB/hash，累计512行预算，1024中1016/4096中4088的旧目标不可达；已知别名read都正确。8确定性案例旧6/8、新8/8，不是模型压缩正确率，也不是新B/C。

新独立SnapshotLiteralAccess：封存公开正文按模型literal精确搜索、source-order无排名，只命中项live ACL/DB/seal校验后返回，缓存不修补坏行。正结果完整性/权限不降；负结果只指sealed snapshot正文，未命中库健康不作证，search_basis/storage_validation明示。原8调用/512 live校验/2MiB正文/16KiB返回不增；新目录最多65536事件/16MiB公开正文引用，扫描每次8192来源/协作250ms，不能抢占ACL/DB阻塞，不称硬墙钟。目录字节统计主机侧，拒绝正文不冒作byte预算失败。

最终仪表测量4096后部：旧构建.142+查询.057秒却失败，峰值1.156MB；新.311+.070秒成功，1.606MB；校验512→1，实际逻辑文本15252→125886。不是更快/省内存，快照/全进程峰值未包含，physical I/O未知，O(N)未解决。默认不改，C-only --snapshot-literal-search新命名策略；可组合预算错误结果与精简运行环境。34定向/6子用例（6文件）过，包含原生工具端口/绑定，独立原库内容/range/hash审计8源DB不变，未调用模型。

证据wsc-late-source-access-20261027-v1；开发profile-v1/v2保留，最终wsc-snapshot-literal-profile-20261027-v3含所有原始搜索输出/审计/测试。0模型计时.657+2.0079374+1.8944947+1.9375665合6.497扣ceil7秒；最新profile-v3/next-admission-envelope.json：23371795/408/11934秒。维护未完整计时仍unknown，旧unknown不重置。v1.23只存代码/报告/小回执，不复制8fixture DB。

下一步晚位旧来源的新预登记真实任务先小额模型资格，确认能用新入口正确续接后3配对，不用原早位build003冒充晚位覆盖，不直接跑75格。新负结果契约/缓存构建成本/资源差异必须单列，未证明模型Token或最终正确率改善。长期goal active。

## 历史：两轮恢复三对系统观测完成，C6/6、B3/6，平均调用多5.4%

[完成报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-two-boundary-mixed-results.md)。原同release-receipt历史/同题：未压缩6/6、B3/6、C6/6；B都当前65正确、旧nonce缺失，C全部正确。完成链路B两压缩+后测均98308.7 Token/41.552阶段秒，C两选材+后测均103587/57.995；C多5.4%Token、39.6%阶段时间。不是热context/金额优势，也不是总体长期保证。

三对混合历史/新增，不是完全同revision前瞻随机对照。复用原B1/B2、C1、R02 C和R03 B；v4 R03 C选材43223/2完整、已导入，因他臂unknown没答题；resume_published_c_query验证绑定/导入/冷资源只补20453/1→2/2。R01新修复资格61890/3→2/2，两个缺失B补123344/5→各1/2。B/C新后测同4/120000/120秒，复用旧1响应未碰2cap结果，标签明示非约束预算兼容。

v4 R01真实第9读取在handler错误适配层外抛quota异常，整个turn中断→unknown；已有目标s6不是没存原文。新独立BudgetResultSourceToolHandler/--budget-tool-results旁路把这一错误转中性success=false工具结果，不增加8次读限、不吞其他错。真实9回调前后0模型回放旧抛异常/新返回错误，前8严格相同、读仍8。38定向/8子用例通过。R01新实测只find1，未触发错误分支，不能称模型超限后续接已证。三条最终C trace各1次，旧/新handler逐字节相同；修复不是隐形改变已接受轨迹。旧handler默认保留，后续新组显式用结果型拒绝，不混称revision相同。

v4新增62331/3（R01失败19108/1+R03选择43223/2）；新资格61890/3；补C20453/1；补B123344/5，合268018/12已知，v4和旧研究unknown保留。605687是6条完成链路含复用合计，非新增/研究总费。所有owner清理确认，source/native父源未改。报告机器JSON/CSV/SVG/PNG在wsc-minimal-recovery-report-20261027-v2，独立评分+回执去重+工具兼容回放；金额/内部context/storage未知。

最新封套wsc-native-recovery-queries-20261027-v1/next-admission-envelope.json：23371795/408/11941秒；维护计时unknown，保守扣留非实际消耗/未知上界。版本v1.22保存新旁路、3个定向复用入口、报告/证据，不复制DB/cold大树。

下一步0模型审计大历史晚位旧证据在512行累计扫描预算下的可达性；再版本/失效或任务切换案例统一精简+新错误结果协议3重复。不重跑本组，不盲全跑75格，不把局部3/6→6/6扩大成所有长期任务。001/011全冷线性与003等边界仍开放，长期goal active。

## 历史：三配对部分续跑，连接与后测限额问题已定位，尚未完成

[续跑报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-minimal-recovery-pairs.md)。同精简C配置，复用R02历史2/2不重跑；已有原B1/B2与C1都不重做。新独立blackbox_minimal_recovery_group执行器封存原source/native线程哈希，原结果/旧unknown保留，非LLM裁判。

v1组三B派发TLS EOF，C额度接口失败，已知0/0但实际unknown，清理全确认。修为协调器先0模型额度检查后统一准入（旧C独立入口检查不改），readiness-v1一度恢复。v2组新已知116732/5：R01B48619/2、R02B43437/2被原后测2响应cap截断无final，不能算错；R03B完整24676/1，1/2（nonce null、current65）。全局unknown正确冻结C，两个C未派发。不能把R03B和R02C跨重复直接配对称收益，三配对未完成。

依实际2次工具后无作答记录，登记B/C后测统一4响应/120000Token/120秒；C选材仍4/200000/240秒，C臂320000/8/360。明确是后测预算调整，不改算法。复用R03B和R02C原完成且未碰旧预算的结果，注明混合历史/前瞻，所有失败/花费另留。新C先并行完成才补B。v3在服务检查再次网络失败，0模型派发，故新预算尚未实际执行。不继续无依据模型重试。

三组group-audit验证source/native父源未变、5个新回执去重/账目一致、unknown/清理保留。37定向通过/8子用例（8文件），非全项目。新脚本/评测修正在v1.21，核心来源端口/精简模型输入保持v1.20。最新封套v3/next-time-reconciled-envelope.json：24691795/444/12098秒，补扣两个准入合0.032秒ceil1；维护unknown。上述Token预算保守扣留不等于已知实际116732或未知费用上界。

下一步等连接稳定先0模型check；通过后新目录补R01/R03 C + R01/R02 B，--reuse-native v2复用R03B，R02C仍用minimal-candidate-v1。全部源/旧失败在原处，不删除usage，不改B，不复跑已完成阶段。具体命令在报告；长期goal active，不能宣布三配对或最终目标完成。

## 历史：来源恢复端口实测后，精简选择器输入，单次资格保持2/2

[本轮报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-source-access-port.md)。可选 SnapshotSourceAccess + native WSCSource：模型提供literal/别名，引擎仅快照/ACL/范围/hash/精确查找，source-order不排名，无语义热选。previous_selection与旧excerpts typed来源引用统一短别名可逆；模型自由文字不改。source descriptor必须绑定offered的session/cut/digest，engine_binding不进模型。35命名定向测试/6子用例通过，非全项目。

复用原R02 C1与同131来源，来源工具版C-only实际4工具调用、2/2、新175347/5响应；精简source_selector_minimal_v1版实际1工具调用、2/2、新61634/3响应。两目录source-tool-audit从独立DB核对来源原文/range/hash，并确认4/4与1/1输出实际进入模型工具结果。owned清理与本地账完整，旧study unknown保留。含复用C1的链路218539→104826，不可重复记新增。

选择器通用启动材料94005→43807B（-53.4%），首次输入32630→18701Token（-42.7%），选材总145362→40926（-71.8%），新增总175347→61634（-64.9%）。整体有调用次数/输出/随机性混杂，只有单次同历史C候选资格，不能称正式3配对或比原生更省。最终答题器/B不改；仅Cselector私有flags替换通用指令/关闭全局记忆、缩技能目录、apps/shell，WSC冷存储不受影响。仍有约36KB通用工具说明未消除，未达最小输入。配置依据官方文档+本地schema；skip_host_skill_discovery仅本地实验特性，不能凭flag接受宣称效果。

证据D:/agent-task-runs/wsc-source-tool-candidate-20261027-v1与wsc-source-tool-minimal-candidate-20261027-v1；零模型source-tool-admission-v1及selector-minimal-runtime-admission-v2/v3。两候选新增合计236981/8；3个0模型计时合8.313扣ceil9。最新封套minimal-candidate-v1/next-admission-envelope.json：25051795/456/12146秒，承接原unknown，保守扣留不是实际消耗/未知上界。v1.19为来源工具版，v1.20保存绑定/精简版与实际证据，不复制大DB/cold树。

下一步登记同精简配置3次正式配对，复用已有C1/B双压缩，仅补C2和B同题后测；不混合不同变体充作重复、不删旧usage/失败、不盲增cap。原R01未知失败/R02未派发/R03旧完成草稿分别处理，不重复旧资格。先三配对报告稳定性/实际Token/恢复/时间后决定推广，长期目标active。

## 历史：两轮恢复组未通过；修复JSON误拒并复用R03完成C-only 2/2

[两轮恢复报告](../reviews/2026-10-27-two-boundary-recovery.md)。新case固定build-003 nonce，129旧来源第二轮无正文/span，新任务依赖旧nonce。三次0模型准入过。首次正式wsc-two-boundary-recovery-20261027-v1因quota接口网络错误0模型终止，复核恢复；quota移为账号级协调器单查，保存故障耗时。付费v2每B有2真压缩、每C第一轮完成：R01 C2搜索记忆/空目录/工具目录触发4响应cap，未完整结束→study unknown冻结；R02 C2准入拒绝未派发；R03 C2完整但request_changed误拒。原v2已知531201/17、uncertain=True，不清零。

结构性修复：previous Excerpt.path tuple经JSON成list，原直接Python比较误拒；native_selection_wire.transport_value派发前冻结JSON，transport_equal严格规范JSON比较且False/0仍不同，非有限数拒绝，大整数保留。native_incremental_compile抽共享纯编译供在线/回执复用，算法/预算不改。27定向测试/6子用例过。

复用R03原完成37517Token选择草稿，验证提交/完成/hash，隔离clone DB编译+stage，0新选材。模型选s6→引擎从source store恢复完整原build-003消息严格相同。wsc-recovery-reused-continuation-20261027-v1实际native导入/冷验证→C-only查询2/2，新增24049/1，清理/账目闭合。不是模型工具读manifest的成功，也不是3次正式B/C通过。该成功C链路101858Token（2选择+查询），整轮已知555250/18且unknown仍在；B后测缺失不可算成本比。

最新封套reused-continuation-v1/next-admission-envelope.json：25571795/468/12294秒，承接v2未知研究；早期0模型28.797+服务复核2.563已在v1/next-time-reconciled-envelope补扣ceil32，v1网络失败20.328及v2执行93.203、C-only约12秒各封套已扣。未计时维护unknown，不能称完整研究精确用时。

下一步先机械核对冷入口可发现性/别名一致性/读取契约，避免selector搜索无关目录；不盲增cap、不关键词排序、不预告标准答案。R02 C2未调用、R03草稿有效且已续接、R01真实失败都保留。不要重跑C1或B两次压缩、不要删usage绕过单边界一次策略。原生最终后测未做，正式三配对未完成。版本v1.16/17保留前置与额度修正，后续修复结果再保存。长期goal active，003/009与全冷目录O(N)边界仍开放。

## 最新：按用户要求优化输入，两个案例质量保持，Token差距缩小

[输入优化报告](../reviews/2026-10-27-compact-selection-input.md)。独立native_selection_wire.py做可逆元数据投影：长cold locator入hash绑定可读manifest，引用短别名/schema不枚举长ID，预算表和明确类型默认值无损编码；正文、来源顺序、417 spans、角色/时间/理解/CAS和必留规则不变。未加语义排名或摘要。用户明确允许引擎处理机械确定项，模糊语义仍模型决定；边界docs/wsc-engine-model-semantic-boundary.md，理解带sources不等于语义证实，空sources当前允许且unverified。

离线三旧草稿roundtrip与Selection编译完全相同，request+schema约435→169KB（-61.2%）。authority新3次实际WSC仍6/6，旧WSC6/6/B3/6数据复用不重跑；C平均219295→100459 Token（-54.2%），C/B3.12→1.43，耗时未明显改善。版本关系holdout新3对：基线/B/C均9/9，B69290/C100127（1.445倍），均正确区分v5源码与v4测试。两组新C六次15/15，范围外正确率/多轮稳定性未证。新增总961663 Token/21响应；首组新301376/6，版本组660287/15。各账目闭合、owned清理确认，有独立compact-wire-audit和JSON/CSV/MD/SVG。

API generate(...short_span_handles=True,compact_wire=True)；group runner/resume --compact-wire；真实worker条件compact_selection_wire=true（配合short_span_handles=true）。全部显式启用，原默认保留。版本v1.14保存代码/离线证据，后续结果版另存；21定向测试通过/6子用例。

最新封套D:/agent-task-runs/wsc-compact-version-group-20261027-v1/next-admission-envelope.json：27471795/524/12453秒，承接compact-wire-quality-v1/next-time-reconciled-envelope（独立准入12.953秒另扣13）。代码维护/未计时检查仍unknown。不要重复本两组或旧简单资格，不恢复退休R03。

下一步验证第二次压缩时旧正文隐藏后的manifest实际恢复与成本，先小规模机械/真实读验证再3配对多轮；不能把一次全新frontier的6/6、9/9当作已证明恢复或最终任意任务正确率。还没比B更省/更快，也没达到全局最小输入。003/009待验证面和001/011完整冷目录O(N)继续开放，长期goal active。

## 最新：第一组真实黑盒三次配对完成，局部保真收益、成本约3.12倍

[第一组报告](../reviews/2026-10-27-blackbox-authority-group.md)。authority第5事件检查点，单次真实压缩，3次并行：未压缩6/6、B原生3/6、C实际WSC6/6。B的R01约束反转、R02两题null、R03正确；C均正确。C均值219295 Token，B70317，约3.12倍，模型阶段平均多22.60秒。已有主要目标的限定行为收益信号，但仅一个小案例，正确率差经验区间[0,1]，不是长期任务或等预算优势。

执行器先遇真实技能目录漂移，修为所有actor共用无业务/无推理bootstrap ancestry，原生算法不改；另遇verify_paths长参数Windows206（遗漏实际预检），先6响应294264已完成，后用独立短命令+sealed manifest+分块hash修复，提前真读，1000项回归通过。blackbox_group_resume不重做原生/基线，仅补9响应726353。全组15响应1020617、3配对，所有owned进程清理确认、同题/父源不改/收据distinct/选材无query字段独立审计通过。失败原目录保留wsc-blackbox-authority-group-20261027-v1，完整续跑wsc-blackbox-authority-resumed-20261027-v1，有JSON/CSV/MD/SVG。18框架测试通过。

最新封套改用resumed-v1/next-time-reconciled-envelope.json：30171795/578/12660秒；另补扣52.124秒零模型准入（ceil53），维护及小bootstrap检查未完整计时仍unknown，旧研究unknown不重置。不要复跑第一组或简单资格探针，也不恢复旧R03。

下一步先0模型审计/实现可逆选材元数据投影，再决定小额验证；R01选择输入193136/输出3394 Token，request380245B+schema54721B，cold_source累计160449B、selection_facts42562B，主成本是输入。不能凭byte宣称分项Token归因，也不能为了赢此题修改语义选材。随后版本关系组3配对，先报告再扩大。WSC热包4.9–11.7KB、持久化1.17–1.20MB，B内部context/storage未知；无等Token或长期稳定性结论。003/009未验证面、001/011完整目录O(N)仍开放，长期goal active。

## 最新：修复后已续正式黑盒案例准备，0模型调用

新增blackbox_matrix_cases.py与test_blackbox_matrix_cases.py：五组authority/version-relations/task-switch/long-distance/expiry-recovery；公开状态规则与私有预定义oracle分开，独立状态解析交叉复核，反例拒绝反转/过期/错关系。12项框架测试通过。计划wsc-blackbox-formal-cases-20261027-v1/matrix.json为3次重复×5组×5检查点=75个配对单元（每个三分支），状态prepared_not_executed，不是已跑75次。报告[正式案例准备](../reviews/2026-10-27-blackbox-formal-cases.md)。

下一步接统一真实矩阵运行器，先0模型检查分支污染/私有答案隔离/同输入/预算/清理，再仅第一组3次正式配对报告，不直接全跑。原生必须真实压缩证明；不重跑2事实资格探针或旧退休R03。上一轮模型预算封套仍为wsc-blackbox-incremental-continuation-20261027-v1/next-admission-envelope.json，没有本轮模型花费；维护时间未完整仪表化，不称全研究耗时精确。代码20项边界见下与专项报告，003/009未验证面及全目录线性增长仍开放。

## 最新：用户WSC-001～020优先修复；首批数据与修复已保存，尚未恢复Benchmark

后续v1.9：否决并撤回stream_v1序列化尝试，失败版v1.8单独保存（22.32秒比旧9.03秒慢且峰值不降）。逐行诊断定位末尾check_binding时完整来源/理解副本叠加；新显式publication_policy='bounded_catalog_v1'/CLI --bounded-catalog提前释放已持久化的解码副本，完整目录/末尾校验/旧格式不变。万条同夹具新进程实测Python60.90→53.14MB，进程167.68→129.89MB，6.664→5.837秒；不是统计性能结论。102/1002/10002均测，全目录仍线性。15命名套件105通过/1跳过/13子用例。003断电、009真实symlink及001/011完整目录O(N)仍开放，不改状态机来刷绿。无新模型调用；继续零模型正式黑盒案例/矩阵准备，不重跑资格探针。

用户明确按正确性/恢复→长期性能→资源→协议取舍处理20项，修完再续Benchmark。报告[20项核验与首批修复](../reviews/2026-10-27-code-issues-001-020.md)，机器表wsc-code-issues-repair-20261027-v1/audit-result.json。当前0新被测模型调用，旧研究unknown不重置。

新增ResourceIO显式旁路：原子不覆盖对象发布、描述符分块I/O、发布期间固定重复对象缓存、Windows文件及祖先目录租约覆盖core.install。004证据改写和019资源os.replace前后已实测旧允许/新拒绝；009删除至open竞态恢复；真实符号链接用例因权限跳过。020普通读失败可恢复、真实子进程退出留下preparing也可status→discard→restage，未复现所称不可恢复P0；不绕过权限或覆盖坏对象。017 recovery_required经reconcile一次宿主效果恢复，008 lookup异常不改旧状态，018为单Store非全进程设计，不改状态机。

prefix_index_v1旁路优化002/007/012：范围前缀校验、一次回填后SQL触发器维护presentation投影、记理解仅查引用IDs。102/1002/10002历史固定cut2实际hash均2条。ResourceIO处理006/010/013/014，8MB比较额外Python内存8.4MB→约0.137MB。全冷发布第一次分块实现变慢也保留；随后固定对象缓存10002规模约17.8秒→6.09秒，全部来源/版本保留，整体峰值约61MB未降。

005/015/016经真实子进程/双流上限前后验证后并入Windows默认JsonCommandGenerator：根CREATE_SUSPENDED→附Job→Resume，超时/超限/完成杀回收后代，不泄stderr。旧legacy=True保留作对照；非Windows默认旧行为未改。共享解析抽selection_transport避免循环，导入无环过。ResourceIO和query_policy仍显式启用，CLI有--resource-io/--prefix-index/export --archive-directory；未把强资源租约默认强加到所有宿主或平台。

最终14命名套件103通过/1跳过/13子用例，非全项目。结果scoped-tests-release.xml。性能三目录wsc-code-issues-profile-20261027-v1、wsc-publication-issues-profile-20261027-v1、wsc-pinned-publication-profile-20261027-v1。原始夹具DB/对象留本地，版本不复制大文件。

下一步先收尾001/011全冷目录线性元数据/61MB峰值及003目录持久化边界；009符号链接实际验证仍受限，不能标全绿。不要删未选中冷证据/历史理解来刷性能，不以fsync注入或进程kill冒充Windows断电保证。之后再统一三分支黑盒正式案例/重复，不重跑旧资格探针、不恢复旧长程评测。长期goal未完成。

## 最新：真实WSC增量选材→原生导入→同题续接通过；资格探针结束

本轮复用前轮原生baseline/compact/post3响应不重跑。实际native_incremental_candidate.prepare + native_incremental_generation.generate(short_span_handles=True) + MODE + IndexedCheckpointAdapter，选择器不见oracle/测题。WSC新增选择21618/1响应、续接20473/1响应，完整42091；三路径同两题均2/2。总复用+新增102382/5响应，不是重复5次或语义优势。

选择1整来源+1span、0新理解；原业务item335B→包1293B，极小输入未见缩减，也未证明语义折叠。使用normal worker审计原生导入后discard，不伪造HostReceipt，不声称原子core.install；冷资源已从native只读实际hash验证，模型恢复行为未测。

v1零模型源未落盘的就绪错误保留（内部cleanup文件确认）；v2生成后过严比较消息ID/传输metadata拒绝，正文/工具一致。修为配置/导入/持久化阶段，复用现有bootstrap_items/import_evidence，仅枚举字段归一化。保留v2生成包、未测题父接收端，只fork补答题，未再选材。证据wsc-blackbox-incremental-admission-20261027-v1/v2与wsc-blackbox-incremental-continuation-20261027-v1。

18项定向测试通过，全清理。最新next-envelope在continuation-v1，32271795/620/12837秒，保守扣250k/12分配不是实际花费、全研究unknown仍保留。实际新增阶段1.515/15.406/9.687秒，不含手工分析，非全研究精确时间。报告[真实WSC黑盒资格](../reviews/2026-10-27-true-WSC-blackbox-admission.md)。

下一步结束简单资格探针，收敛统一矩阵运行器，用预登记冲突/失效/版本/干扰历史作三分支至少3正式配对；显式区分真正缩小、实际恢复和仅接口成功。先审判据/资源，避免白跑；不恢复旧长程方式，不改语义算法来迎合测试。长期目标未完成。

## 最新：用户修订黑盒行为方案；真实原生小额链路通过，尚非WSC对照

优先以用户黑盒规范为准：无需读/解密摘要，被测Agent输出结构化答案或执行确定性操作，程序评分，无额外裁判LLM。有证据可自行修改方案，保存旧结果版本。旧大任务退役不恢复。

在线zero-call capability通过：同父兄弟分支有效历史hash相同，模型/effort同、父源不改、清理为空。wsc-blackbox-native-admission-20261027-v1。随后唯一小额native smoke：baseline答题20143、真实压缩19995、post答题20153，共3响应/完整60291 tokens/15.594秒。两支同题各2/2，compacted+同turn绑定回执+durable终态+原生terminal共同确认，无读摘要。不是难题、不是收益统计、没有WSC对照。目录wsc-blackbox-native-smoke-20261027-v1。

封存后预算结转报错（诊断上限和父研究上限混用），进程exit1；真实业务已完成与清理，原result保留。blackbox_budget离线投影修复，不重跑模型；保守扣300k/10分配，next envelope32521795/632/12865秒，旧unknown保留，实际花费60291，准入零模型耗时未计入阶段账明确标注。

评分器跨task事实覆盖已修（修前1fail/9pass），CLI区分执行和质量失败并支持质量失败重放；真实删除启发/合成版本两个反事实8格完成，固定旧来源负对照分别1/2错、实际read恢复后0错，不归咎正常选材。blackbox+机制共17检查过。报告[黑盒能力与修订](../reviews/2026-10-27-blackbox-benchmark-feasibility.md)。

下一步把黑盒接口接现有native_incremental_candidate/native_incremental_generation真实选材/安装，再做同小历史原历史/原生/WSC三支。不以JsonCommandGenerator或固定全选替代当前算法，不把前版白盒弃判当黑盒不可评分；基线和测题应兄弟隔离，多轮主干不接受测题。当前goal未完成。

## 最新：用户详细规范下的确定性Benchmark MVP已实现；未完成真实原生配对

独立wsc/benchmarks/deterministic_v1，README列实际调查、接口和限制。9项定向自测过。真实core.prepare/stage/read、public-only适配输入；所有压缩完成前无oracle/评分落盘。精确结构化字段/关系评分，自由文本及加密弃判，不用关键词。固定全选/空选是机制控制，不是语义压缩算法；stage-only不伪造安装，不把identity历史当原生。

paired-mechanism-v2同5轮/2噪声，两种机制10格全部完成、各10问正确；cold-v2空选热593B/10问弃判，真实read后各10问正确，I/O13/13906B→49/55434B，恢复262144B不是等热预算收益。早期full-v1两格view预算失败保留。真实B-seed-v2归档1原生边界导入，但输入不匹配paired=false。全部0新模型调用。

实际原生API compact/start存在；摘要加密不可评分，内部模型/温度不可确认；本机无tiktoken/tokenizers，不用字节冒充Token，不声称等Token/实际Codex对照完成。可选generator正常接入接口未跑模型。图和逐格JSON/CSV已输出，图已查看。报告[确定性MVP](../reviews/2026-10-27-deterministic-benchmark-MVP.md)。

下一步连接真实删除/版本案例与正常选材器、验证原生等价可观察协议后再选实验；不扩大矩阵、不恢复旧R03。整体任务尚未完成，原失败/unknown/成本不清空。

## 最新：用户废止旧长程评测，继续修复已暴露问题；不要恢复R03

用户明确停止当前评测方式，偏好不依赖模型，同时明确旧问题仍需修。原cohort/evaluation-method-retired-20261027.json记录retired_by_user、automatic_resume_allowed=false；goal继续，不是暂停目标。不重启旧v2/v3、不为补足三次继续付费。

新方案见[无模型评测与修复](../reviews/2026-10-27-model-free-evaluation-and-repair-plan.md)：真实轨迹状态转换、隔离oracle、同预算反事实/变异、真实WSC接口；机制/信息充分性/真实Agent效果三层分开。加密原生语义不可判定，不拿离线历史基线冒充原生Codex，不靠关键词或来源ID评选主目标收益。

三次C共6压缩边界均为加密compaction，语义不可直接审查。实际R02工具证据：680确认preload删除不存在→698压缩→709引用旧文件→712模块缺失→716重建→719成功。行为错误已证，摘要丢失因果未知；WSC只初始注入，后续无持续WSC发布。audit在D:/agent-task-runs/wsc-continuity-boundary-audit-20261027-v1。

本轮修复cleanup漏最终消息：observe_final由既有显式旁路启用，绑定thread/turn、过滤final、消息ID去重、复制保存，不更改默认B或清除超额。修前实际execute_stage合成回归1失败/2通过；修后相关16通过+10子用例。另真实core删除当前资源回归正确拒绝旧live引用且保留历史摘录，未重复修已有能力；不是修好模型行为。

下一步实现首批artifact删除/源码版本更换的无模型反事实案例，先验评分器能拒绝故意错误，再测当前WSC实际导出。保留修复债务及旧unknown，不再堆长程调度补丁。长期目标未完成。

## 最新：第二组结算与开销离线复核完成；不放宽未知门禁

wsc-R02-cost-review-20261027-v1：两边closed-native保留阶段前缀且回执逐条相同，B关闭源仍只有turn_aborted。B唯一account_turn原因是正常完成证明缺失，不是已观测到的累加缺口；不能将下界改为完整或加调度补丁绕过R03。此次0模型、未重跑验收。

C普通86响应/5701837 tokens，3压缩315578（总量内）；B普通53/6095639下界。可见工具文本排除图片后B232758字符/C462825，源码读搜词法调用19/40、验证相关14/32（类别重叠，非精确归因、非全部浪费）。C三次输入95952→26516、95974→24833、93831→24074；单次输入下降未转为已证实总体收益。启动仅一次WSC包，后续均原生内部压缩，不是反复WSC主动更新的证明。

下一步复用三次既有C归档，核对压缩前后当前源码/已验证状态是否被丢失并导致补读；找到具体缺口才集中修订方案，不继续堆调度补丁或新大额重复。原未知、上限和停止门禁全部保留。报告[成本与结算根因](../reviews/2026-10-27-R02-cost-and-accounting-root-review.md)。

## 最新：第二组已关闭；两边17项与滚动通过，均超预算，第三组未启动

execution-v3/R02：B原生53响应/已知6095639/755.218秒，interrupted、无最终回复、完整用量未知；C89响应/完整6017415/948.593秒，3次自动压缩，completed且有最终回复。两边官方11+并发失败3+图表日期键盘3及滚动均过，收窄定位诊断也过；两边仍registered_token_cap，资格均false，无经济收益或稳定优越性结论。

C原completed=false是收尾观察漏更新：主循环越限先退出，随后cleanup收到completed却未同步outcome。独立native_cleanup_terminal可选旁路修复，真实execute_stage合成前后对照保留超额/用量；与计时和准入共9检查过。实际R02零模型回放仅新增独立audit，原phase/result等hash不变；B仍false，C派生true，超额不取消。证据D:/agent-task-runs/wsc-R02-terminal-review-20261027-v1/audit.json。

控制器86439已exit0，无活模型，R03未启动。next-repetition-admission拒绝usage_unknown。最新封存envelope剩余32821795/642/12881秒，pair实际墙钟984.766秒；非账户余额或未知上界。当前B/C私有workspace仍为R02最终源码，未restore，不可当S2；不要重跑旧v2/v3脚本或重生成种子，也不能新建空账绕过未知。

下一步离线核查预算中断后的用量结算可靠性，保留B未完成和旧未知，再复核第三组准入；此之前不新开大额重复。未来恢复须先保留R02差量、精确恢复S2、读实时额度、登记新目录。报告[第二组结果与记录修复](../reviews/2026-10-27-second-fixed-S2-BC-pair.md)。原第一组报告已交付，五任务三次未完成。

## 最新：调度停止规则已修，execution-v3的第二组B/C运行中

独立native_repeat_admission模块阻断服务错误/未知用量/在途或清理和来源异常后的自动下一组，纯功能失败仍为样本。4检查过；真实旧三组回放会在R01断流后停止，避免后4请求，不声称节省费用。新循环保存next-repetition-admission，不能以新envelope绕过本登记的未知。旧所有记录不改。

独立源码副本定位复核：scope-locator-review-20261027-v1，hash绑定三组旧源。筛选栏内定位+直接图心值检查，旧资格C仍3过、R01B仍失败、R01C从定位阻断变3过。原官方/补充结果与资格标志不改，新增诊断不抹去C未交付/旧读数标识失败。后续原计分与诊断同时记录。

用户明确“按实际实验运行时间累计，额度等待不计（推荐）”，adoption在cohort/execution-time-policy-adoption.json。native_execution_time两检查过，不按mtime扣停机/额度等待；最后封存13880秒扣实际零模型操作约13.882秒→13866秒，token44934849/响应882不变，旧失败/未知/原上限不改。启动前零模型账户读取primary17%且可用，两侧S2精确1162文件匹配。

**当前活控制器：**exec会话86439，run_fixed_S2_repeated_BC.py，结果根D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1/execution-v3。R02/B、R02/C已运行，之后只有准入通过才R03。原S3、两份固定状态、两侧原评分与原6M/120/2700不变，原第一组不重试。不要启动旧31262、不要重跑准备或新运行脚本，运行中不要改ROOT/src或experiments的py与固定grader/driver（pins锁定）。

下一步轮询同一86439与execution-v3/R*/pair-result.json、next-repetition-admission.json、cohort-result.json，分别统计业务响应样本、完整成本样本和通过数。若观察超时先查原handle，不能重启。报告[本轮准入和定位复核](../reviews/2026-10-27-repeat-admission-and-locator-review.md)。尚无新对照结论，五任务目标未完成。

## 最新：第一组无C优势；B部分验收未过，C断流未交付，后两组额度拒绝

exec31262已返回exit0，controller PID7644已不存在。execution-v2/cohort-result.json行政completed_pairs=3，但有效业务样本仅第一组，不能当三次有效比较。第二、三组B/C都usageLimitExceeded，未有模型响应，已知0但完整未知，旧记录保留，不自动重跑。

第一组B正常完成、完整2419391 tokens/25响应/535.156秒；官方11/11、并发失败3/3、滚动过，但成本图筛选中心仍¥1.50未按登记口径变¥1.20，图表组未过。C未正常完成，已知2163092/31响应/1376.953秒/1压缩，完整未知；官方10/11、并发失败2/3，旧读数标识缺失；C03/图表组因9模型控件匹配而阻断，不将未执行断言全部称功能错误。C实际日志responseStreamDisconnected/websocket closed before response.completed，控制器按无自动重试结束，不能归因WSC或温度。两侧同质量完整成本条件不成立，较低C已知token不是省，当前无相对原生收益证明。

用户要的第一组报告：[2026-10-27第一组报告](../reviews/2026-10-27-first-fixed-S2-BC-pair.md)。R01/first-report.json/md是最初自动数据投影，人工复审报告补充了定位阻断和后两组已结束的当前状态，以人工报告为准。当前B/C源码已被控制器为后组恢复至S2，第一组实际源码在R01/preserved-final-B|C/changed-source.zip及retained-extra，不能读当前workspace当R01源码。

下一步先校验定位口径、编排遇明确服务不可用后停止后续调度，保存全部失败/未知及新版本；不再启动付费调用，直到额度实际恢复且新的重复登记就绪。额度阻断不是三次有效结果，不能扩大预算或丢记录。原goal保持active，未达成；当前不是活进程等待，勿重启旧31262。

## 最新：三组固定状态B/C已登记，execution-v2第一组正在并行

根目录D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1。B/C工作区均已保留旧差量并恢复1162文件精确S2，复用原实体依赖/浏览器。发现原B只拿较早公共事实、C有后补校准；从原C源库提取6条原始观察给B原生压缩前输入，没有拷贝WSC生成理解。双方底层材料与原S3请求固定。

B-seed第一次为零模型祖先层级断言错误：比较了capsule父包装层hash而非实际root_history，记录保留。B-seed-v2核对继承原始root完整hash后通过，默认native idle compact，完整197577 tokens/1响应/59.156秒，源码不变且清理为空。原生B没有96000覆盖。B这份原生压缩状态与C原32765字节包各固定，三次只比较续接波动；不覆盖压缩生成波动。C76397只是最后增量选材，全部历史准备成本仍未知，不能称C全准备只花76397或0。

首次并行预检R01捕获C循环变量key覆盖预算臂名，B/C都未turn/start，0模型、0token，所有进程清理。记录在根R01与cohort-result.json，是行政启动失败，不是有效任务结果。修复为独立native_package_media.dependencies、独立arm_key和请求前双侧二次barrier；8媒体实际hash验证过。修正运行写独立execution-v2，旧记录不改。当前冻结代码和源pins禁止运行中修改。

**当前活任务：**run_fixed_S2_repeated_BC.py，exec会话31262；最近write_stdin确认仍运行，R01/B、R01/C均已业务启动。execution-v2自动按R01→R02→R03执行，每组两侧并行，结束后同17项与滚动验收，再保留差量精确恢复S2进入下组。每臂原6M/120/2700不变，独立结果与完整费用保留。每组关闭后沿既有qualification_envelope保守扣分配/保留未知；不恢复旧未知账本，不将未用分配称实际花费。

下一步仅轮询同一31262和execution-v2/R*/pair-result.json、cohort-result.json，不重跑任何准备/运行脚本，不重生成B/C种子，不改冻结代码。观察超时不是退出；若handle失效，先查controller进程及实际结果再决定。三组结束后核对全部失败/未知、固定状态成功率与用量；要区分早压缩与WSC语义仍需同阈值原生诊断。不是五任务八阶段矩阵完成。

## 最新：C真实S2→S3资格通过，转正式对照准备

wsc-a3-dev-C-auto-compaction-20261026-v1。原精确S2/原S3/同32765字节包，无再生成；96000 C旁路、原6M/120/2700。正常最终回复、完整4197357 tokens/62响应（60普通+2压缩）/666.984秒；输入4148454、缓存3926528、未缓存221926、输出48903。压缩204836已计总账；前后普通输入95679→24856、94958→24094。原生同turn会计完整，未活动外部compact/重建。

官方累计11+独立并发/失败3+图表/日期/键盘3=17过，生产面板真实滚动正常无裁切，已看图，验收期间源码不变。GUI digest04dd2f9fc37a82beb4acecdf7077df2affb772775802e7e6bb218c0517d7ec48。6个实验GUI文件变更，不合主GUI；不是全项目build/原组件套件或八阶段完成。pins不变、所有原生/浏览器自有进程清理为空，旧未知仍冻结。

历史旧C6035553已知/44响应/985.860秒未完成，本轮已知token低30.46%、未缓存输入低16.40%、输出低32.71%、观察阶段耗时低32.34%；只是两次单次C记录、旧完整未知，没有B/重复或费用因果证明，普通响应反而更多。组合C此S3正确续接和上下文缩减已证，WSC语义相对原生增量未证。

运行前六文件备份zip+7旧验收目录整体移入新OUT保留，265额外文件核对；私有依赖/浏览器身份不变无复制。1162文件精确恢复S2后才启动，原请求与包复用、SQLite只读backup。现在C已是新S3，不能照S2清单重跑；旧S3材料在retained-S3-*，源hash/映射已存。独立审核移除一个未使用的全工作区扫描，避免今后重复哈希大依赖，没有重跑模型。

下一步：正式同S2 B/C登记，各3次并行、对称基线事实/验收器，B默认不改；同阈值原生诊断用于区分压缩时机与WSC增量。当前探索C不追认正式样本，五任务三轮未开始。最新准入见本OUT/post-review-admission-envelope.json，原臂未用1802643/58仍保留非实际花费，旧未知不清零/上限不提高。报告[本轮真实结果](../reviews/2026-10-26-auto-compacting-C-S3-result.md)。

## 最新：工具跨压缩访问证据补齐，转原S2/S3业务准备

native-post-compaction-access-20261026-v1：单次两turn共用服务/thread/同预算，先原生自动压缩后第一turn完成，再独立请求write_stdin原session1078，真实返回原PID24900/nonce/新心跳；第二步未起新进程。startup exec yield和wait均实际配对，审核最初硬计两call漏wait，按实际三call修正，没有模型重跑。两阶段完整6响应/156789，压缩49039，52.844秒，全清理。仅一个PowerShell会话/32000 fixture能力，不是全工具或96000业务资格。

native_c_auto_compaction.py新增显式C开关，资格hash/来源hash/CLI/model/effort/features绑定后仅追加96000启动阈值；默认settings值不改、真实worker B job拒绝携带。4新+3既有检查过。wsc-c-auto-compaction-policy-v1通过真实hook零模型config/read96000，origin=sessionFlags，未写配置/未turn。原生B不改，旁路不是已证实收益主链路。

只读S2恢复计划：C相对1162文件初始manifest有6变/0缺/265新增，6变都能从冻结S2精确恢复。新增约54.6MB包括旧S3结果/图和validation/node_modules，需识别文件/链接归属并保留后移出，防后续材料污染；不能盲删/追链复制。工作区本轮未动，依赖未复制，选材未重做。计划在policy-v1/s2-restore-plan.json，paid_execution_permitted=false。

下一步：保留旧S3差量和新增材料后精确恢复C至S2，复用实体私有依赖/浏览器、原32765字节包和原S3请求，登记本版旁路/验收/累计预算后一次C资格；不能直接重跑旧driver、从S3起步或再做同类协议问答。最新policy-v1 next-admission-envelope87334849/1734/19185，非余额/旧未知上界。未来仍须区分原生更早压缩与WSC增量，五任务三轮未开始。报告[访问与C旁路](../reviews/2026-10-26-post-compaction-access-and-C-policy.md)。

## 最新：原生同turn自动压缩+正常继续已证；跨压缩工具访问仍未证

native-auto-compaction-20261026-v4：原CLI/model/effort，独立启动32000阈值（仅fixture，不改未来应用96000候选）。3响应/88803 tokens，其中压缩48120，compacted和latest回执绑定、同thread/turn正常最终输出，完整会计。无活动外部compact/inject。PID25980在压缩前/后Job均存活、最终清理为空；不是后台工具访问完整证明。

模型在唯一外层exec内同时启动并write_stdin，output先于compacted；压缩后只有最终消息，没有工具调用。最终state_survived=true基于压缩前轮询，不能当跨界正例。独立audit-v2据源顺序拒绝升级C资格。

v1是py不可用的真实前置失败：2响应/46767、完整、无压缩。v2/v3是零模型预检拒绝自定义outputBytesCap/绝对Python路径，均未turn/start或预留。v4 PowerShell脚本readOnly预检成功后才调用模型，未放松权限。全部旧失败保留，本组实际模型总135570/5。

result两个false初始标志未更新的控制器记录缺陷已在当前脚本修正，原冻结result及运行controller快照不改；独立audit-v2绑定原hash才是结论。早期audit的str(list)/one-byte描述错误保留，v2以内容块正文52323字节修正，不推断送达丢失。

下一步：新的单次小额登记，在同一存活服务把压缩后原session访问设成独立请求，不能与启动合并；通过后才原S2/S3的C资格，不直接开6M、不重跑旧目录。正式B不改，需区分原生调度与WSC增量。最新v4 next-admission-envelope87491638/1740/19239，旧未知保留，非余额或未知上界。报告[自动压缩实测](../reviews/2026-10-26-native-auto-compaction-result.md)。长期主目标与五任务三轮未完成。

## 最新：不继续堆终止重建；原生内部自动压缩存在零模型配置入口

v0.4仍缺启动即归属、停止后工作树绑定、后台会话迁移、真实原子安装/lookup。旧C已知输入95.55%缓存，重建可能增加成本，先不实施。原v0.3严格门禁和旧故障不改。

native-compaction-feasibility-20261026-v2：同绑定CLI的default/仅启动model_auto_compact_token_limit=96000两次config/read，默认null，覆盖实际96000且origin=sessionFlags。没有turn/start或配置文件写入，模型0，服务清理。官方配置文档确认该键用途，但自动压缩运行时/执行状态保留/收益仍未证明。v1因带入旧workspace browser_cache在settings guard拒绝，0进程0模型，原失败保留；v2只选本审查所需会话字段，没有放松私有路径检查。

历史44回执达到64k/96k/128k的首次序号4/7/18、响应数41/38/27只是历史报告计数，不是触发或可省量。报告[可行性v0.5](../reviews/2026-10-26-stage-compaction-feasibility-v0.5.md)。

下一步：准备一次小额同会话原生自动压缩能力验证，检查compacted+压缩回执、正常续接、工具配对及执行状态，不发活动外部compact/不重跑动态checkpoint/不开6M。通过后才考虑原S2/S3的C资格；正式B不改，未来需原生同阈值诊断区分时机与WSC增量。最新next-admission-envelope在native-compaction-feasibility-v2：87627208/1745/19309，旧未知保留，非费用余额/未知上界。五任务三轮和主要收益仍未达成。

## 最新：真实root-only门禁不可达；未中断，停止该路径付费重试

native-controlled-stop-20261026-v1唯一小额协议尝试，匹配checkpoint/回执/生命周期其余条件成立，但Job有root+5子进程，门禁拒绝。没有interrupt/活动compact或inject，没有stop seal。中性不可用回调后普通完成2响应/45308 tokens/13.719秒，普通会计完整、全清理；task_completed仅指微型协议请求。原生B和默认执行不改。

native-idle-process-inventory-20261026-v1零模型、无turn/start：initialize空闲也有conhost；空闲thread又有node_repl，CIM与Job成员一致。证明不能以无子进程代替排空；旧等待点的5子进程具体身份仍未知，不凭名称放行。v0.3离线19过不是真实正例可达证明。

下一步：停止root-only付费重试，先离线审查[终止后封存v0.4候选（未实施）](../reviews/2026-10-26-controlled-teardown-design-v0.4.md)的执行归属、工作树和真实安装合同；不能用假root-only调用旧seal。新接收重建缓存损失必须计入收益权衡；关键原语不足则讨论方向，不继续堆模块/再跑6M。报告[实测结果](../reviews/2026-10-26-controlled-stop-real-result.md)。最新next-admission-envelope在native-idle-process-inventory-v1：87627208 tokens/1745响应/19310秒，非现金余额/历史未知上界。旧未知/失败不改，正式矩阵未开始，目标仍未达成。

## 最新：受控边界旁路19项过；旧v3仍拒绝，不等于真实原生交接

experiments/native_controlled_boundary.py新增保守等待点准入、显式interrupt封存、停止事实，以及已确认发布/实际空闲新受体导入后的原StudyBudget预留；默认原生执行和B不改。CallbackHost仅离线夹具，真实原生原子安装/持久化lookup尚未实施。专门19项过，不是全回归或任务收益。

离线重放D:/agent-task-runs/wsc-controlled-boundary-guards-20261026-v1：旧v3缺当时进程成员证据，实际门禁拒绝；仅反事实root-only结构检查之后，旧关闭来源仍因另起压缩执行拒绝。未追认旧成功，原记录hash不变。目标原文已重新读取C:/快捷方式/临时文件/`12.md。报告[受控边界旁路](../reviews/2026-10-26-controlled-boundary-guards.md)。

下一步：一次新小额显式interrupt实测，同步Job成员/完整生命周期，禁止活动compact/inject，不重跑旧probe或大额S3；成立后才实施真实原生接收HostPort和lookup/reconcile。沿用native-boundary-v3 next-admission-envelope及旧未知，不能把未知清零或重置预算；本轮0模型，无新模型用量扣减。正式B/C矩阵仍未开始。

## 最新：动态等待点有回执；活动compact替换原turn，安全原地交接未成立

native-boundary-capability-20261026-v3，唯一一次有模型协议尝试，上限120000/4/120，无推理重试、无业务开发。匹配dynamic callback被暂扣时有1条22497 tokens回执（输入22449/输出48）；事件流可见dynamicToolCall，thread/read同刻只列user/reasoning，不能当全工具图。

活动inject返回接受，但关闭后没有测试marker，持久化/送达未证。活动compact返回接受，原turn reason=replaced，中止外层exec，另起压缩turn。探针只等原turn终止即关闭服务，新压缩turn22ms后被中断，未观察compacted/完整用量。该控制器不足已记录，不算压缩成功或证明接口绝对不可用。1已知响应/22497、完整未知冻结、全进程清理；未用97503/3保留，旧账本/CLI hash不变。next-admission-envelope 87672516 tokens/1747响应/19327秒，非余额/未知上界。

v1/v2为rollout尚未创建的启动前失败，未发turn/start、预算臂未启动、0推理；普通执行事实注入后才封存源解决准备问题。另有语法修正在执行前。都保留，不重跑旧probe/改写未知账本。默认NativeApplicationSession仍拒绝未登记server callback，原生B不改。

下一步：基于[受控检查点v0.2（未实施）](../reviews/2026-10-26-controlled-checkpoint-design-v0.2.md)核对排空/显式原执行结束/完整来源/空闲受体导入和提交，再构造旁路。复用native_host_checkpoint与successor的前缀/冷祖先逻辑，但其receipt=None不是原子安装证明，不能绕过。停止活动回合compact原地替换与大额开发重跑，不启动正式矩阵。报告 [原生等待点能力](../reviews/2026-10-26-native-held-boundary-capability.md)。长期主目标仍未达成。

## 最新：校准包C/S3仍触6M；17项功能过，转阶段内上下文结构审查

D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1。相同S2/原S3请求/32765字节包，无重新选材，上限6M/120/2700不变。985.860秒、44响应/6035553已知token（缓存5697408、未缓存输入265465、输出72680），registered_token_cap、无最终消息、完整未知；超出35553保留。pins不变、进程全关闭。选择+本开发已知6111950/45响应，非全研究量。

最终独立11+3+3=17过，生产面板正常1440×1000可滚动，无裁切。GUI hash efdb86c2d5f107dbdfe41c6af5a4d5486cfa3696001b7e2b05e39839d563f15e。6个实验源文件改动，原task-contract/vite配置/原组件测试不变，未合主GUI。没有原组件套件执行再追9失败，但不能归因仅WSC。C03角色定位后有源码变化、中心值和标签再修改，复测不全是多余。

构建出现.vite-temp EPERM、runner __dirname、缺pet.html；冻结S2与当前均缺配置引用的pet.html，配置hash同，未重跑基线build。环境探针范围不覆盖所有构建缓存路径，不把这些都归WSC。

首输入32083→末188875，均值135520，窗口258400，无压缩响应；44个实际外层工具输出4个截断。相对固定首输入参考增长4551221仅算术，不是无损可省量。边界后直播阶段继续增大是新重点，不继续堆状态问答。已离线导出同CLI experimental schema，看到compact/inject/interrupt/steer等，但安全活动回合替换/完整结算能力未证实。报告 [本轮结果](../reviews/2026-10-26-calibrated-c-s3-result.md)，[结构提案（未实施）](../reviews/2026-10-26-stage-context-redesign-proposal.md)。

下一步：停止同类付费开发，先只读审查原生安全边界、动态工具等待点、输出送达覆盖，再实施经可行性约束的阶段内投影/压缩旁路。不提高6M、不缩任务、不追认本次截断，不启动正式矩阵。next-admission-envelope 87792516 tokens/1751响应/20563秒，旧未知/76未用响应保留，非账户余额。整体目标仍未达成。

当前paired-evaluation-admission的C/workspace已是本次S3源码，不能继续按旧S2绑定直接跑；B/workspace仍为S2，实体deps/browser原地保留，旧执行脚本不要重跑。

## 最新：一次增量选材完成；组件校准进入理解，实际采用尚待开发验证

D:/agent-task-runs/wsc-a3-calibrated-selection-20261026-v1。一次响应/76397 total tokens（输入70323、缓存0、输出6074），75.125秒，回合/用量完整。原12/180/400000不变，无重试；所有进程关闭，source/pins不变，无开发调用。

独立native_equivalent_selection_replay通过公开API将未发布选材状态重放到同S2新C副本：201事件、4理解版本、身份/修订/producer/控制源计数及选中正文不变；旧Store hash不变，不改绑定SQL，不导入活动发布状态。修正初始guard/JSON容器检查与SQLite连接close问题，3项针对性检查及真实重放过，中间失败DB保留。不是通用运行恢复。

追加两个新源后cut203。热视图32765字节（原20151，+62.6%），body69894，8整源/19片段/4理解/5线索。三类旧理解保留，组件校准27/9、定位副本36/0、语义负向3失败进入新增理解；旧verification@1未再与@2重复进热状态。完整用户控制源保留，引用/片段hash过。材料105文件、导出326文件原生只读哈希过。

宿主差异在热完整事实中明确：旧inner-body裁切 vs production-panel可滚动；旧理解仍保留历史裁切描述，没有单独修订为新视觉理解。selection_evidence_gate_passed=true仅证明证据可用/范围保留，模型实际采用和完整C续接未证明。报告 [增量选材](../reviews/2026-10-26-calibrated-incremental-selection.md)。

下一步：停止选材/状态问答辅助探针，复用本包与已准入C实体运行目录，准备实际S2→S3续接登记、核对累计预算和验收范围；不重做S1/S2或自动启动旧6M/正式矩阵。next-admission-envelope为93828069 tokens/1871响应/21809秒，旧未知保留（边界未用323603/11保留），非真实余额。未来B/C须对称收到同一校准事实，原生B压缩不改。长期目标未达成。

## 最新：可写B/C环境通过；九个既有失败已在独立定位副本验证

D:/agent-task-runs/wsc-paired-writable-admission-20261026-v1。复用两套已关闭实体依赖/浏览器：common-prefix B与selection C分别移入paired-evaluation-admission的B/C工作区；四次移动、0大目录复制，目标旧联接/空占位已按计划移除。两侧原生workspace-write并行：自己写成功、跨副本EPERM、通用浏览器探针及实际A3新宿主/真实滚轮通过；GUI仍173fc5…，24.532秒，0模型，全进程清理。paid_development_permitted=false，不能自动转开发。

原组件36项27过/9失败直接原因：7旧文案/定位、2错误信息多匹配。只改定位的独立副本保留同36测试名/断言数，应用代码逐文件不变，36/36过；故意把accepted:false映射已验收仍报3失败，已恢复。原冻结测试不改，原9失败记录不追认成功。component-calibration-observation.json与pending-S2-observation-event.json准备好、未入模型，不能泛化为所有旧失败都是测试问题。

旧未知/失败与账本hash不变；next-admission-envelope.json保守扣本轮墙钟后为94228069 tokens/1883响应/22471秒，非实际余额。下一次从此承接，不能沿旧23037重新起表。报告 [可写准入与定位校准](../reviews/2026-10-26-writable-pair-and-component-baseline.md)。

资源现位于D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1/B|C/workspace/gui/node_modules及.wsc-runtime/browsers；都是实体私有。旧common-prefix B和selection C的deps/browser已缺失，旧源码/证据保留。历史component-source-ab联接指向旧selection，不能照旧跑。

下一步：结束环境扩展，复用正确理解追加本轮事实，准备一次增量选材更新，检查是否正确区分宿主现象/旧定位失败/当前缺陷，再评估实际C续接预算。不直接再开6M、不重做S1/S2；正式五任务各三轮B/C和总体收益仍未达成。长期目标原文C:/快捷方式/临时文件/`12.md不变。

## 最新：成对评测已接入；只读原生接收过，可写开发未准入

D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1。独立native_paired_evaluation通过显式开关接prepare/grade/public binding及shared-S2 worker；B在原生压缩前得到事实，native_compaction不改；C记入同一事实源。默认路径不改。3392字节事实只含S2，不含后续C实现。两侧原生只读会话实际注入相同事实、三份冷引用哈希过，无token回执，进程全清理。模型0、正式B/C0。

执行上下文v2把可执行宿主文件身份与含绝对路径的来源描述分开，跨私有目录同文件仍相等，真实执行字节变化仍失效。旧v1不改/不升级，重新生成一次S2 v2观测。7项context/3项worker/2项shared-worker过；实际adapter.grade走新宿主S2 9/9。独立C前沿事实一致不是完整C选材/开发证明。

两个零推理副本复用只读依赖联接，inference_permitted=false；不能拿来直接跑可写开发，原生内部浏览器本轮也未验。随机端口6667曾被浏览器拒绝，失败保留、只继续一次零模型检查；分配器未改。原生启动前空cache目录缺失也已记录，继续脚本创建后接收成功；主驱动补准备/未启动清理判别但未整轮重跑。不要盲目重跑已有admit脚本，所有输出exclusive。

预算沿最近C失败账本承接：准入94228069 tokens/1883响应/23037秒，旧73未用响应保留；历史用量未知、旧账本hash不变，不是实际剩余额度或未知账单上界。报告 [成对接入](../reviews/2026-10-26-paired-evaluation-integration.md)。

下一步：停止扩展只读收口探针，先零推理确认可写隔离和原生浏览器能力，再评估新S2事实对真实续接的预期信息增益并登记；不自动追加6M或正式矩阵。三次完整C未正常收口，五任务各三轮B/C及长期成本优势都未证明。长期目标原文仍在C:/快捷方式/临时文件/`12.md。

## 最新：零模型上下文校准已验证；尚未接入正式成对driver

用户已提供迁移后的目标原文C:/快捷方式/临时文件/`12.md，本轮完整阅读；最终标准仍是持续正确工作、恰当补证、总体成本值得，八组目标不缩减。不要再读取已失效Desktop路径。D:/agent-task-runs/wsc-evaluation-context-20261026-v1/goal-source.json记录新来源哈希。

新增独立native_evaluation_host + native_evaluation_context旁路：现存A3SnapshotPanel带PageShell入口；观察在执行前登记GUI/辅助文件/宿主/入口/探针/场景/视口，复用时重算。旧source-only helper/default不变，不事后升级旧观察。六项单元检查过；两次真实几何/滚轮观察S2/C都可滚动，错入口和改宿主字节拒绝过；新宿主C累计11/11过，原宿主/业务源码不变。0模型、没有重跑组件基线、没有完整视觉或B/C收益结论。

paired-S2-facts.json为2438字节事实，仅冻结S2（173fc5…）和其既有组件基线；不含后续C代码。组件27过/9失败只描述原测试副本，未把旧失败全判为测试缺陷。旧失败/未知保留。这个校准尚未集成正式prepare/grade，不可宣称当前worker已经使用新条件。

下一步：通过显式开关把新宿主/同一S2事实接双方prepare/grade，先零推理验证输入对称、入口、引用与预算承接，再评估下一次模型信息增益，不自动重跑6M或正式矩阵。报告 [上下文校准](../reviews/2026-10-26-evaluation-context-calibration.md)。

## 最新：增量包C/S3再触token上限；17项功能通过，旧组件失败和宿主裁切已作零模型对照

D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1。零模型源码/浏览器/314冷文件准入通过，原样注入20151字节包，不重新选材，原2700秒/6M/120不变。实际693.812秒、47响应/6019477已知token，registered_token_cap、无最终消息、完整用量未知；超额19477保留。源码pins不变，进程关闭，旧失败/未知冻结，正式B/C未启。此最近选材222309+增量70588+开发6019477=6312374已知/49响应，非全研究量。

独立最终S1—S3 11/11 + 并发/失败3/3 + 筛选图表/日期/键盘3/3通过；最终GUI清单590baa4a6ad1523f5e619f3bd90d87f62de91386f768df04853306c33c9858f2。完整C资格未过，不证明相对B收益。原task-contract不变，7个实验源码/测试文件未合主GUI。

零模型原组件测试A/B：同一原测试在冻结S2和当前均27过/9失败，无新增/消除失败。原生收口追查了既有失败，但不能把全部成本归因此或都判为测试缺陷。

关键纠正：原宿主只渲染UsagePageBody，漏掉实际A3SnapshotPanel的PageShell，root隐藏溢出导致裁切。旁路仅改宿主入口、不改业务码/冻结断言；冻结S2和当前均能真实滚动，不裁切。原裁切观察是宿主事实，不是已证实产品缺陷；此前适用范围判断过宽。只绑GUI源码不足以区分宿主/入口，后续追加事实须含其绑定，不手改旧模型理解。

下一步：停止追加付费开发与B/C，先零模型校准旁路宿主/入口和组件基线；新条件另版本登记、B/C对称，不改冻结原件。再复核累计预算和继续价值，不自动重跑6M。报告 [实际续接与基线复核](../reviews/2026-10-26-incremental-c-development.md)。

运行目录提醒：复用的D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1/workspace已变为本轮C源码，不再匹配旧S2观察；历史selection检查不能原样重跑当当前证明。冻结S2在common-prefix/staged/frozen-workspace，私有deps/browser仍在selection workspace；所有模型已关闭。

## 最新：一次增量修订已保留裁切诊断，候选语义复核通过

D:/agent-task-runs/wsc-a3-incremental-visual-20261026-v1。复用incremental-review-input，不重做开发或首次选材。一次响应/70588 total tokens（输入65916、缓存0、输出4672）、44.234秒；回合和本次用量完整。原边界12/180/400000不增加，旧失败/未知及累计预留保留。源码/pins不变，所有模型进程关闭。启动前已有浏览器目录创建错误发生于0调用，准备记录保留在同名-preflight-only目录；没有重复选材。

原200事件和三条理解原样保留，只追加有当前源码绑定的裁切观察；verification_status显式新增第2版。热视图6整源/11片段/3线索，17022→20151字节，body44142字节，均在原限额。三个理解身份有四个热版本，旧验收第1版和第2版并存有冗余，未观察到冲突，未手改模型文字。

具体裁切诊断在整源/理解新版本/线索/片段均存在，保留正常场景1440×1000与full_visual_qualification=false；S3目标、9/9仅自动、原S2回合未完成、不同manifest范围均保留。原时间/片段哈希/所有引用检查过；当前源码绑定重核过；原生冷读103/314文件哈希过。semantic_selection_gate_passed=true，仅本候选复核，不是完整开发通过或B/C收益。全部研究用量未知保持。

下一步：先用新封存包做零模型开发前准入（工作区/runtime/宿主/冷证据/累计预算）；通过再单独登记有界C/S3实际续接及裁切风险复核，不直接启动三轮B/C。报告 [增量修订复核](../reviews/2026-10-26-incremental-visual-selection.md)。

## 最新：阶段/范围错误纠正、热视图缩小，但具体裁切观察仍待增量修订

D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1。只一次选材，1响应/222309 total tokens（输入216994、缓存0、输出5315），53.25秒，回合和用量完整；原边界12/180/400000未增加。原199事件完整保留，追加范围/阶段事实；原错理解未手改。新可选schema补manifest_scope/delivery_stage，旧默认不变，格式1/worker3/shared1检查过。

热视图47771→17022字节，5整源/10片段/3理解/2线索。三条理解已正确写S3和不同范围4cd…工作区/173f…GUI，9/9不扩成完整视觉或原生回合完成。导出/引用检查和311份原生冷文件哈希过，源码与运行期间pins不变，进程关闭。不是整个旧状态无损压缩，不是B/C收益或开发通过证明。

新稿仍只保留视觉未验收，未热引用具体裁切诊断。零模型在同一冻结S2实测1440×1000：报告高1586.9375，祖先裁切、没有纵向滚动通道、真实滚轮不动；源码未变。因此该关键观察仍适用。完整冷证据在，但不能据此称语义复用已充分，development_gate_passed=false。

已准备 incremental-review-input/state.db + offered.json + previous.json：保留当前三条正确理解/线索与原事件，追加有gui/src绑定的当前裁切观察，0新增模型。下一步仅一次小额增量修订，检验该具体负面观察是否保留且绑定/阶段/未知/原时间正确，再决定开发；不重跑6M或自动启动三轮B/C。

私有依赖/浏览器已从sharedtime工作区移到本轮workspace；旧业务源码/证据保留。当前是只读选材注册，不能盲目当开发注册重跑。报告 [本轮选材复核](../reviews/2026-10-26-scoped-selection.md)。

## 最新：共享时间仍触及 token 上限；确认哈希范围混淆与阶段理解错误

两轮独立 C 开发均从同一 S2、同一原选材15整源/34片段重导出，原事件与摘要不变，没有新选材调用；依赖/浏览器已按关闭记录移动到 D:/agent-task-runs/wsc-a3-dev-C-sharedtime-20261026-v1/workspace，旧业务源码和证据未动。旧目录的浏览器/依赖位置已缺失，不能照旧路径盲目重跑。

固定600秒轮 D:/agent-task-runs/wsc-a3-dev-C-20261026-v1：42响应/5685419已知token，600.063秒中断，独立11+3过。公开首次11/11在271秒但非最终源码，最终版本到589.6秒才过，因此不能把后续检查都视为多余。

用户明确选择普通阶段共享本臂剩余时间；每臂仍2700秒/6M/120响应，全研究与边界不变。新共享时间轮：653.640秒，41响应/6093677已知token，token cap、无最终消息、完整量未知；独立11+3+3=17过。全部进程清理，原生回执无迟到/改写，三轮B/C未启动。不得恢复任何旧未知ledger、自动追加同样开发试验或提高token上限。

离线检查原选材：热线索仍说“当前请求继续S2”；理解记录把整个工作区清单4cd7…与GUI/src回执173f…当成不同源码，错误否认同一S2源码9/9回执。逐文件证明GUI hash正是173f…，package/lock也匹配。9/9仍不是视觉或原生回合全部完成证明。

新增可选 native_scoped_selection_state：scope+算法显式、不同scope不可作版本比较，S3交付阶段事实、保留旧时间/视觉未知；prepared.scoped_selection_state启用时两侧收到事实，C登记为新源事件。接收代码变成S3时拒绝旧S2作为当前证明。3项比较测试+worker3/shared1及真实S2/不同S3来源校验通过，0新模型；未重生草稿、未手改旧理解、未宣称修复语义有效。

下一步：仅一次小额阶段感知选材生成，核对错误理解是否纠正、关键负面观察/未知是否保留、热状态与引用是否合格，再决定开发准入；不再直接跑6M。报告 [真实开发准入](../reviews/2026-10-26-real-development-admission.md)。

## 最新：必要事实的真实模型状态交付通过，结束收口辅助验证

D:/agent-task-runs/wsc-a3-capsule-review-20261026-v1。原生新只读接收线程，复用1279字节事实和哈希冷索引，不恢复41响应开发历史。任务只要求基于既有事实交付状态，不重新开发/验收或调查历史依据，与旧核验任务不同，不作因果成本比较。

登记2响应/90秒/60000 total tokens、自动重试0；实际1响应、12.641秒、24261 total tokens（输入23046、缓存0、输出1215），正常完成且本回合用量完整。外部8个事实字段匹配，源码/运行期间pins不变，关闭原生回执匹配、所属进程清理为空。模型保留原S3超时、历史用量未知、B/C收益未证明，未伪称全项目验收。fact_delivery_passed=true，但 full_S2_to_S3_qualification_passed=false。

选材/续接/收口链已知5961238 token /46响应，不含共同S2开发成本；历史完整量仍未知，原6M仅余38762已知空间，不扩额或再做相同收口测试。三轮B/C未启动。辅助事实交付到此结束，后续回真实开发续接，先冻结任务/公平条件/累计预算再登记，不能用本次交付代替开发准入。详见 [本轮报告](../reviews/2026-10-26-capsule-fact-delivery.md)。

## 最新：宿主已接入双方；只读收口超 token；小范围事实接入仅零推理通过

D:/agent-task-runs/wsc-a3-closeout-20261026-v1。fixture_transport 显式旁路接入 prepare/grade 及共同前缀/边界 runtime 事实；B/C 两侧原生烟测通过，新宿主 C 累计 11/11，源码仍与旧额外六项一致。默认与冻结原件未改。fork 显式 read-only，模式 3 项、worker 3 项、shared worker 1 项通过。

本次 C 只读收口独立登记 3 响应/120秒/600000 token，未重新开发或选材。72.031 秒 registered_token_cap，3 响应 / 644921 已知 total tokens，完整量未知、未交付。整笔超出量保留，源码和运行期间 pins 不变，所有进程关闭。原选材 + S3 + 收口链已知 5936977 /45 响应，完整量未知；原6M仅余63023已知空间，不自动追加模型调用或扩额。旧两个失败 result 不追认成功，三轮B/C未启动。

额外消耗的直接编排问题：简单核验却继承完整开发历史并注入全源码清单。新回合每次输入约21万；73,443紧凑JSON字节的事实清单也进入注意力。新增可选 native_review_capsule，17项精确事实1279字节，完整清单/回执冷存；实际新只读接收钩子无history_base，8份/508748字节冷证据哈希通过，篡改拒绝，0新增模型调用。只证明接入和证据，不证明模型收口成功，不是开发历史完整压缩或相对B收益。

原S3功能17项通过保留，完整S2→S3准入仍未过。后续先以必要状态作为新登记输入，明确任务范围/预算；不得复制旧整段历史收口方案、恢复未知账本或自动重跑已有driver。见 [本轮报告](../reviews/2026-10-26-c-closeout.md)。

## 最新：C/S3 独立功能 17 项通过，但 600 秒阶段超时

执行目录 D:/agent-task-runs/wsc-a3-c-continuation-20261026-v1。复用共同 S2、实际旧草稿包，不重做开发或选材。41 新响应 / 5,067,941 已知 total tokens；原 C 选材 224,115 继续保留，合计已知 5,292,056。600.032 秒中断、完整用量未知、所属进程全部关闭。原登记 C_S3_diagnostic_passed=false，不启动三轮 B/C，不追认旧失败成功。

独立累计 S1—S3 11/11，加并发/失败 3/3、图例联动/日期复位/键盘 3/3，全过，业务源在验收中不变。得到压缩上下文下产生可验证 S3 功能改动的局部实证；没有完整回合、全部任务、旧观察语义复用因果、相对 B 成本/时间收益证明。

模型自编检查多次定位器纠错，r4 曾五项过；之后并行复测遇到 Vite 默认 WS 24678 冲突，r6 收口被中断。新增可选 native_fixture_transport，派生宿主把 WS 附着各自随机 HTTP server，零模型两实例前后旧失败/新全过。冻结原件未改，该宿主尚未接入模型输入。后续先登记并接入双方测试宿主，处理验证回圈，不能恢复未知账本、放宽原条件或直接自动重跑。见 [本轮报告](../reviews/2026-10-26-c-s3-continuation.md)。

## 最新：同一 S2 压缩首轮结束，C 无损表示修复已验证

共同 S2 代码/历史分叉，只研究压缩续接，不重做 S1/S2。D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/result.json：B 原生压缩完成，S3 在 600 秒限额中断；C 选材完成，编译 view_byte_budget_exhausted。已知 17 响应 / 1,380,492 total tokens，完整量未知，所有进程关闭。共同 S2 自动验收 9/9，但原生 S2 回合中断。

新增可选 source_reference_view / native_indexed_checkpoint，由 indexed_checkpoint 显式启用。同一真实 C 草稿离线重放，body 135731→109645，native items 99245→47840 bytes，仍在原 131072/49152 限额内；15 source / 34 excerpts、全部还原事实及其他原生项目不变。新增及相关 15 项检查通过。原生零推理导入所供字段不变，333 份冷文件实际只读哈希通过，业务源码不变、进程清理为空。

没有重新选材，没有新增付费调用，也没有 C 业务续接或收益结论。原 result 不追认成功。下一步单独登记 C 同草稿续接诊断，保留共同 S2、旧失败/未知及累计预算；不得重跑已有 prepare/register/run 或恢复旧未知 ledger。见 [shared-S2 报告](../reviews/2026-10-25-shared-s2-compression.md)。

## 最新继续：2026-10-25 实际浏览器通道修复、调用前准入、v3在途

当前驱动validation/matrix-runtime-20261025/a3_pilot_v3.py run，会话18314；输出D:/agent-task-runs/wsc-a3-qualification-20261025-v3。源码工作区复用v2零模型调用的干净副本（路径仍在...qualification-v2/arms/B|C/workspace），仅移动各自私有浏览器运行目录到工作区根.wsc-runtime；两侧实际目录的原生零推理启动/本机HTTP/截图已通过，业务源码初始哈希未变。输出与浏览器资料目录独立新登记，普通阶段共享本臂token和响应余额；本臂6M/120响应/2700秒、普通阶段600秒与边界限额不变。

v1准入87004已退出0：B/C均S1响应32上限、共64响应7,397,340总token，完整量未知；未到任何压缩。此次补查发现此前遗漏的环境障碍：原生workspaceWrite无法从用户浏览器缓存启动，出现EPERM并引发替代通道探索。相同浏览器字节复制到私有任务根并配置进程级PLAYWRIGHT_BROWSERS_PATH后，原生default/full启动、HTTP和截图均通过；版本151.0.7922.34，不修改全局权限。

有界真实模型工具探针确实执行成功，生成浏览器结果/截图，但第四响应后被四次上限中断（此前3次memory/脚本/目标检查），故已知4响应96,755 token仍为未知完整量；不重跑它凑结束证明。只读冷文件见证哈希通过，非未来全部冷源的保证。真实A3夹具在旧B部分源码上原生执行C01也通过，仅能力验证、不追认任务成功。

v2准入99495因依赖目录内runtime/checks写权限，在调用前被拦下，两臂推理0、账本确定0；之后在已关闭目录内移动runtime，B/C各自零推理复核通过，不重复制。新增native_application_capability在普通初始/每次新开发fork、模型调用前验证浏览器能力；失败先清理，不消耗业务模型。

后续准入已把旧四臂24M额度、v1两臂12M额度、四响应探针160K额度（已知+未用留额，不冒称未知花费上界）、5响应117,973完整协议消耗及执行时间全部带入，剩余143,722,027 token/2871响应，时间继续扣减；总研究180M上限不增加。原账本冻结且whole_campaign_usage_complete=false保持。

接续18314和已有输出，禁止重跑已有prepare/register/run、改动运行中的绑定Python源码或自动启动正式矩阵。目标仍为真实八阶段/三边界/外部累计验收，再做实际人工界面审阅。完整说明见[本轮报告](../reviews/2026-10-25-a3-qualification.md)。

## 当时记录：2026-10-25 用户授权后首次A3准入（已结束）

用户已明确同意上一条四步安排。新增旁路native_campaign_envelope保留旧v3完整用量未知和冻结状态，把旧四臂原24M/480响应完整额度（含已知3,156,889/52和未用留额）及5个协议准备响应117,973 token、已有执行时间带入后续准入额度。剩余155,882,027 token/3,115响应/27,888秒，原全局上限不增加；留额不是未知费用的估计或严格上界。4项检查通过，旧账本及结果未改写。旧原生当前文件与封存字节一致，没有新回执。

仅启动a3/qualification1 B/C，目录D:/agent-task-runs/wsc-a3-qualification-20261025-v1，驱动validation/matrix-runtime-20261025/a3_pilot.py run，会话87004。prepare/register已完成，输入两侧均为新鲜冻结源码、私有物理依赖副本；两侧初始准入matched=true，已进入S1。普通阶段可申请本臂剩余token，总臂上限6M/120响应/2700秒不变，其余阶段响应/时间及边界限额不变。

禁止重复启动prepare/register/run；接续现有会话和输出，真实模型运行期间不修改已绑定的src/experiments Python文件。目标是八阶段、三次真实B/C边界及外部累计验收；单个包生成不算通过，之后需实际界面人工复核。首阶段宿主技能动态刷新仍作成对检查；旧协作组两侧刷新不同，未追认有效。缺失回执或新未知继续冻结本次准入，不自动重试失败，不启动剩余正式矩阵。

详见[本轮报告](../reviews/2026-10-25-a3-qualification.md)。当前尚无完整任务/三边界准入结果，也没有WSC质量等价或收益结论。

## 最新结算：2026-10-25 首轮触发阶段预算，未到B/C压缩分化

v3首轮四条S1均触发750,000总token上限，尚无完整阶段或压缩边界；已知52响应、3,156,889总token，包含缓存输入2,563,840、未缓存输入494,391、输出98,658。A3 B/C分别769,586/802,995，协作B/C分别823,102/761,206。所有已知回执与关闭后的封存原生文件逐ID/数值匹配，无迟到/重复回执，四个所属进程树均确认清理；turn_aborted不是完整账单证明，complete_usage=null、uncertain=true保持原样。

关键是固定单阶段额度截断了前期阅读和首次实现，并非C压缩失败。正式有效组0，其余十三组未启动。不要重跑study.py run、review_wave.py或package.py，输出以独占方式写入，已存在。driver只支持首轮，不能为了后续波次重新创建预算而丢掉旧消耗/未知。

validation/matrix-runtime-20261025/first-wave-review.json已结算真实首轮；study-conditions-v4-proposed.json是未启动提案。新旁路native_application_budget_policy将普通阶段token申请量调整为可用本臂额度，仍受每臂6M、全研究180M、响应/时间限制和并发预留约束。四份同源前缀离线重放旧分配触发、新分配尚未触发；0新推理，不能证明任务能完成。v3仍冻结，不能借新登记绕过未知账本；下一步需安排保留旧未知/已知消耗的累计预算与不中断的实际任务/三边界准入，然后才考虑后十三组。

实际运行源码167份Python及边界证据已封存versions/20261025-native-matrix-runtime-v3-delta.zip，SHA256 afd7a03009dc566a92d327ad786764bfcf9aefc4bb4f0c63023a10edf8357148；该包捕获于首轮在途，最终账本和未启用预算提案另行封存。当前多出的预算提案模块未在这次真实worker中执行。完整记录见[报告](../reviews/2026-10-25-native-matrix-runtime.md)。

## 当时记录：2026-10-25 原生八阶段接通、启动差异修复、v3 首轮在途（已被上节结算覆盖）

当前真实驱动：validation/matrix-runtime-20261025/study.py run，登记与输出 D:/agent-task-runs/wsc-application-matrix-20261025-v3。仅执行 wave 0：a3/r1、collaboration/r1 四条轨迹，其余十三组已登记未执行。首轮已通过两组初始工具/配置一致性检查并进入 S1。先接续查看会话25593与已有输出，禁止重新启动、覆盖回执或改动运行中已锁定的 src/experiments Python 源码。

完整说明见 [本次报告](../reviews/2026-10-25-native-matrix-runtime.md)。新增多层 fork 逻辑位置/物理行分离、精确父链封存；C 候选 incremental_recorded_spans_v2 修复完整源标识与别名的命名契约，并绑定上一视图的修订、线索和引用。真实 v1 草稿在旧版 quote_source_missing、v2 成功，未重生成语义。之前真实准备新增四响应共95,406总token、金额未知，只证明小边界，不是完整应用收益。

v2 首轮四条全部在模型调用前失败，ledger responses=0、tokens=0、uncertain=false。原因是工具外层随机编号误比较，以及实际插件安装工具说明在两进程间漂移。记录全部保留，不能算十五组有效样本。旁路只忽略 message/additional_tools 外层编号，保留工具定义逐字检查；双方显式固定 recommended_plugins=false/tool_suggest=false。四个并行零推理启动同上下文、均清理；真实工具说明差异依然拒绝。新 v3 复用 v2 零执行私有输入前重新验证源/依赖及封存回执，输出目录独立，避免重复物化。

worker 已接入三次边界、累计预算、独立阶段回执、原生 compaction/选择/fork/import 与外部验收。自动项通过且缺人工证据时仍待评审；未知消耗冻结新调用，不重试失败。driver 仅执行首轮，完成后核对终止/全回执/账本及实际界面，然后再实现保持累计预算的后续波次入口，不能为下一批重置消耗。当前没有十五组结论，没有 C 质量等价或收益结论。

## 最新继续：2026-10-25 增量候选、A3输入、累计预算与质量条件冻结

C候选incremental_recorded_spans_v1已在validation/application-freeze-20261025/study-conditions-v1.json登记，绑定实现与核心源码清单。新增native_incremental_candidate：新阶段文本+旧源冷入口+模型明确保留的理解修订/原文；不再自动把上轮整段assistant消息装入下轮。模型可修订记录、显式留旧片段；旧观察时间/hash/版本不升级为当前结论，rendered上限49152字节、body131072、material2097152，超限/非法选择不回退也不重试。5项检查含三次实际导出，均discard且不冒称host安装；没有实际模型选材或收益证明。

新增native_application_budget/quality。累计预算：普通阶段32响应/600秒/750000总token，边界12/180/400000，每臂120/2700/6000000，全研究3600/28800/180000000（含缓存输入，不等于费用）；所有生成/压缩都从同臂扣。并发预留不重复花已预留额度，超额整笔计，未知保留已知并冻结新调用。质量要求当前源码/辅助包、完整自动项和有证据人工项，单自动通过不能变完整应用。质量组件首版实际复现“外层CURRENT绑定包装OLD登记仍通过”，已同时核对原登记/结果/单项回执/同运行目录；前后passed→unknown，源版本留存。当前预算/质量9项通过，加候选5项共14项，详见final-check-scope.json。

A3输入D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1已完成：824源码/任务文件、41935依赖文件、656671688字节。先前串行复制因实测吞吐被明确停止；第一次并行resume的containment断言失败，具体瞬时路径未记下，静态复查未发现越界。最终预校验目录/相对清单、逐文件源目标hash完成，复用41887文件，只补48；不重复已验证复制。实际Node24.14.0/React19.2.8/Vite6.4.3/Playwright1.62.1及Chromium二进制已pin。src/package/lock与原A3验收基线精确相同，未重跑旧截图。依赖与每臂私有副本无hardlink/junction共享可写状态；实际私有物化待worker。

计划三次边界S2/S4/S6：B用原生压缩后native fork，C用sealed初始bootstrap native fork+精确WSC导入，双方均native fork以减少接入混杂；真实compaction/选材尚未接入。新增零推理boundary_transport_probe已用既有一次付费协议线程验证full-parent和initial-parent双fork，继承1/0响应，已观察host配置相同，C事实注入原值匹配，另开read-only选择线程被接受；父文件不变、0新增响应、所有进程已退出。该检查未调用compactor/模型选材，不证明完整边界或模型wire等价。

本轮0新增模型响应，正式5×3研究未启动。下一步直接接完整矩阵worker（fork结算、实际compaction、只读selection、三个边界、质量出口和累计ledger），做准入后启动首批；不再重跑上述基础校准/旧截图/旧JSONL题。所有句柄终态，无等待任务。长期目标active。

## 最新继续：2026-10-25 新原生版本执行层与输入冻结

旧6257d9e8f63c0f2b/codex.exe已不存在；当前2993767bd1dfb009为0.164.0-alpha.11.1。新增native_owned_process可选JobObject进程所有权，native_application_session可选实际原生阶段执行/追加回执结算，以及native_application_inputs明确白名单输入冻结。旧NativeRPC入口不改。四原生服务实际同时就绪、成员集合互斥、关闭后空；初始检查因空线程rollout不存在保守失败，保留原result，reviewed-result另存。独立零推理试验确认：idle无文件，注入事实后产生11条/132438字节完整历史，0响应，不重跑四路。

新会话实际打开成功；2个合成阶段检查验证错回合completion不会提前完成、断连会落盘且禁止继续。唯一新增付费探针：D:/agent-task-runs/wsc-native-application-phase-20261025-v1，1响应、22567 total tokens（input22542/cache11776/output25/reason14）、2.734秒；完成/结算完整，JSON ready=true，工作区不变，金额未知。该探针只验证新版本新模块的协议与结算，无工具或压缩，不计B/C成绩。

付费探针后的审核发现cleanup异常会跳过账本落盘；保留其源码before-cleanup-guard.py.txt，新增异常保护。针对性前后检查证实旧版0条journal/无落盘，新版1条journal/回执存在并保留cleanup错误；未重跑付费探针。final-review.json明确paid版与当前版源哈希和唯一差异。

四应用各15文件已冻结于D:/agent-task-runs/wsc-four-app-inputs-20261025-v1；含starter、八阶段请求、公开验收/人工程序，不含作者后端/其他任务/缓存。只证明包内白名单，未证明OS拒绝读取外部答案。A3及依赖未冻结。模型luna/max与二进制观测写入suite-draft，但候选、三次边界、累计预算、全矩阵worker协调和最终质量接入未完成，ready仍false。不要把四服务并行称为四条模型轨迹完成；不要重跑协议测量。下一步集中冻结C策略和边界、A3输入，接上累计预算及质量出口后启动首批两组成对。长期目标active。

## 最新继续：2026-10-25 四任务成功路径和具名故障校准完成

新增公开extended_cases与四个作者专用HTTP校准后端，模型起点不含后端答案，核心src与生产GUI/python未改。真实运行结果：imports 9/9、booking 6/6、files 6/6、collaboration 6/6，共27项成功路径；11种具名故障均被预期检查检出。总15个纯本地校准变体、102项检查，review.py核对167次服务启动/停止、回执哈希、执行源码与起点不变，未重复旧起点检查、无新增模型调用。证据validation/five-task-calibration-20261025/review.json及外部wsc-*-positive-calibration-20261025-v1目录。

选定故障为：未知变零、重复入账、替换解码；旧通知发送、重复投递；删除复活、丢历史、冲突块接受；忽略版本、部分批次、迁移重置。未把故障变体视为模型失败或经济收益。作者校准后端只供协议测试，未实现完整界面，也不是合格模型交付。正向检查与故障检查使用同份公开验收可执行字节；之后新增覆盖说明与人工审核文档，不重跑已有执行。

四任务的完整UI、部分分页/迁移/中途崩溃边界仍依manual-review.md逐项留证，不能把27项当全需求完成。作者材料未进入starter；尚未验证原生worker对外部作者文件的读取隔离，不宣称安全盲测。准备阶段到此不继续追求穷尽参考实现；下一步集中做真实并行worker、最终输入范围、WSC候选及边界和预算冻结，然后首批两组成对。A3新增控件正向路径及人工流程仍需接入。正式5×3研究尚未启动，长期目标active。

## 最新继续：2026-10-25 四应用起点与代表性HTTP验收

此前中断后的prepare.py已完成，未重跑。四个任务各8阶段的公开说明、固定API和隔离starter已落盘于benchmarks/application-five-task-v1/tasks。collaboration只复制旧starter，不含calibration作者答案。新增acceptance/runtime.py/cases.py/run.py，实际启动服务、记录请求响应并管理直接子进程；外部总时限/后代进程治理仍待worker承担。

首轮四任务并行本地校准：D:/agent-task-runs/wsc-four-app-starters-20261025-v1，17项中4启动项通过，13项因未实现API/迁移读取404失败；不是13个新bug，后续成功分支并未执行。所有17个服务启动/停止PID逐项核对，起点源码未变。验收后只明确files合同中删除对象PATCH404并同步task.json，保留原运行合同哈希，不伪称运行过最终合同。覆盖缺口见acceptance/COVERAGE.md，人工界面和全阶段覆盖待补。

新增模型调用0；不重跑这批起点来凑证据。5×3正式研究未启动；接下来集中补四任务关键缺口与成功分支校准、共享浏览器验收，再完成真实并行worker和候选/预算冻结。A3归档版本20261023-a3-browser-acceptance-v1-delta.zip为52192字节，sha256 fa05e6b1c869a6e009c6c0cdbc22898a8d87b22219ff51377f07d372e5413aa2。长期目标保持active。

## 最新用户任务：五个长任务，每任务三组并行对比

用户进一步明确“A3算一个任务，其他再来4个任务……每个任务执行3次”。最新范围为5任务×3组成对重复=15组/30条轨迹，替代之前A3单任务至少5组的本次安排；A3的S1-S8合起来算一个任务，不把阶段当重复。当前准备清单[五任务方案](../benchmarks/application-five-task-v1/suite-draft.json)：A3、项目工单协作、文件资源中心、数据导入报表、预约通知。其余四个题材是当前代理拟定的代表性选择，用户未分别指定题材；可以后续调整，但不需再确认已明确的5×3数量。

新增native_task_matrix旁路：每任务固定三组、五任务共15组；默认2组成对/4臂并行、任务类别交错、共8批。按任务分别结算，14个有效组也不能掩盖某任务缺一组；质量失败/超预算计有效观察并保留费用。16项离线检查通过（新矩阵7项+既有调度9项），含30次合成worker各运行一次。验证目录validation/task-matrix-20261023，活动Python源码147文件；没有真实原生worker并行或WSC收益证明。

A3可执行验收及选定故障校准已完成，记录validation/a3-acceptance-20261023/review.json。首次完整运行21项、18项通过，未通过的C07/C08/C10是新增供应商区分、双导出和显示偏好要求，不能算原版退化。两个内存故障注入均被实际浏览器抓住：未知费用改0、旧日期响应覆盖新日期；生产GUI源码不变。导出纯校验器接受4个合法样本、拒绝10个损坏样本。最后定向运行C06/C07/C08/C11，原版异步与大数据通过，新增控制仍缺失；没有重跑最终源码的全部21项。C11交互耗时与开发服务首次启动分开，实际筛选/切日/明细/搜索各小于1秒。

完整浏览器正向校准仍未完成：新导出、供应商选择、偏好控件尚无实现，后续成功分支没有浏览器证明；C11-C14人工项目待审。末次执行后仅修正人工覆盖投影包含browser_and_manual，记录了版本边界。保留race-v1故障注入器匹配次数错误，不能归为产品故障。所有浏览器进程已结束，新增模型调用0；不重跑既有基线。接下来补其余四任务起点与公开验收、实际原生worker、候选和预算，不把验收器校准当WSC收益。

用户已明确确认“是，重做项目里的 A3 界面”，目标为A3NativePanel/A3SnapshotPanel用量页面。任务要求有代表性、足够困难且够长，并要求界面更好看；不再等待或重复询问A3指代。TeamFlow原型和作者校准代码仅为已放弃扩展的未验证草稿，不是当前任务，不启动其模型实验。

已新增[A3八阶段任务草案](../benchmarks/a3-ui-long-v1/task-draft.json)：覆盖视觉重做、主题与响应式、筛选异步状态、会话明细、多供应商同名模型、导出快照、性能与偏好、最终交付；提出S2/S4/S6后三次边界，但边界协议及预算尚未冻结。此草案ready_to_launch=false，不能当正式实验登记。A3按最新要求执行3组成对重复；全研究完成五任务准备、冻结候选策略、实际运行配置与总预算后启动15组对比。

native_repeated_pairs.py可选模块已通过9项离线调度/结算检查，记录在validation/repeated-pairs-20261023。旧单参数worker接口真实复现“产生合成回执后异常，最终结果丢回执”；旁路改成worker(job, record_phase)，逐阶段独立落盘，异常保留已知消耗且完整总量保持未知，B/C分别统计含失败的全部消耗和每成功任务token量。新接口检查的baseline失败包含接口不兼容，不能把全部失败数量称为9个旧bug；before-failure-reproduction.json才是旧API丢回执的直接证据。尚无真实原生worker适配、进程清理或付费四臂并行证明，不能据此宣称十条轨迹已启动。

A3隔离浏览器基线已完成：`D:/agent-task-runs/wsc-a3-ui-baseline-20261023-v6/result.json`，会话31352退出0，4场景/13截图，0模型调用。实际导入当前GUI组件及HTTP解析，以合成HTTP数据覆盖正常、部分未知、空账本、503失败；固定时间/时区、明暗主题和1440/1024/390宽度，明细展开前0次请求、展开后请求选中日期。生产gui/src全清单前后相同，未连接实际账本或后端。Vite6.4.3、React19.2.8、Playwright1.62.1、Chromium151.0.7922.34记录在回执；包声明范围不能代替安装版本。

预览准备失败均保留：v1模块导出加载错误，v2/v3开发依赖加载超时，v4已渲染但等待器误选隐藏SVG title；v5截图停在内部滚动中段，不能作为首屏视觉基线。v6已将首屏复位及明细截图分开，检查过桌面首屏、窄屏暗色、明细、部分未知和错误态截图。部分未知费用的环图中心读数拥挤已纳入共同视觉要求；不代模型改生产界面。现有入口仅为基线捕获，不是八阶段验收器，不要再运行已完成的基线来冒充新增证据。

最新重复要求已落到[重复与并行规则](BC-REPLICATION-POLICY.md)：5任务各3组，共30条独立轨迹；默认2组/4臂并行，隔离工作区、端口、浏览器与可写数据，完整报告失败与费用。三次重复帮助观察波动，不保证消除方差或统计显著。旧单次结果不补写为重复研究，旧单任务五组入口保留兼容性但不作为当前研究完整性判据。

## 最新继续：两次原生续接重复对照完成

[完整报告](../reviews/2026-10-23-native-repeat-results.md)。`D:/agent-task-runs/wsc-native-repeat-20261023-v1/reviewed-result.json`确认两个原生分叉在相同保存历史、代码起点、请求、公开验收、工具和可见配置下，均完成有限数值阶段10/10及产物/报告审核。会话17367退出0，不再等待或重跑；目录B/C只是旧快照助手的存储槽，两臂实际上都是原生N1/N2，没有WSC C。

N1为7响应/159.157秒/286467 tokens，N2为10响应/136.625秒/400050 tokens；N2输出+7.71%、耗时-14.16%、总tokens+39.65%、非缓存输入-42.57%。新增共17响应/686517 tokens，完整回执与归档核对一致，金额未知。父累计576406仅作继承起点，不再收费；旧父文件及旧工作区保持不变。两次结果不能估计总体随机分布或单独确定温度，也没有比较非原生接入方式，不能与旧B/C直接合并。

原生自身也出现路径和工具错误差异，停止把旧单次+9.44%当WSC因果缺陷。另已拆解旧用量：全成本输出增3480而推理增6115，输出减推理余额下降14.59%，但包含B两次压缩；只看任务阶段该余额增加9.10%。不能把输出tokens当最终回答字数。详细原始回执绑定在native-repeat验证目录，旧成绩未改。

活动源码仍143文件，本轮仅新增研究驱动和记录，新共享phase已实际跑通两次付费分叉任务。研究准备版本20,160字节。不要补跑同题凑波动范围；下一步回到原消息跨代增长、摘要与可核查证据分工的候选设计，基于已有失败与使用轨迹确定收益假设，再登记新策略实验。C旧质量缺口、长期稳定性与经济收益仍未解决。

## 最新继续：分叉准入和新增用量旁路

[完整报告](../reviews/2026-10-23-fork-admission-and-accounting.md)。已把登记的单层父历史、实际线程设置、当前文件清单和本地执行事实接入显式fork_append_only_turn路线，默认路线不变。新增native_fork_phase，首轮继承父累计起点，后续用本地最新累计；父响应不重复计费，父文件执行中变动判无效但保留新费用记录。44项相关检查通过，源清单143文件；不是全项目检查或收益证明。

唯一付费协议测量在`D:/agent-task-runs/wsc-fork-admission-20261023-v1/single-response-probe`，会话97908已退出0；已有分叉收到只读JSON请求，1响应/26955 tokens/28.313秒，无工具、工作区不变。回执累计继承576406，界面累计继承526494，新累计分别603361与553449。原result.json待审计状态保留，reviewed-accounting.json更正；最终源码离线重放与原回执相同，0额外调用。实际付费调用是独立驱动，新的共享phase仅离线事件测试，不冒称真实任务验证。

旧输出+9.44%和时间+10.08%仍混合随机性与接入差异，有效temperature/top_p/seed未知，不能归因于WSC。下一阶段才是登记有限原生重复对照；当前没有新对比运行。不要重新运行observe_resume.py或measure_first_receipt.py，现有分叉已包含一次协议测量，不再是空的刚分叉状态。长期目标、C质量缺口和原消息状态增长仍未解决。

## 最新继续：原生分叉审计与只读历史重建修复

[完整报告](../reviews/2026-10-23-native-transport-and-history-projection.md)。用户提出温度/非原生接入混杂：两臂可见模型设置相同但有效采样值未知；原生B原线程与C新线程同时改变了策略和接入。已复用旧stable-carrier的同原生状态研究，没有重做不透明值导入或启动付费对比。

真实零推理审计`D:/agent-task-runs/wsc-native-transport-audit-20261023-v1`：归档路径分叉被原生分页身份校验拒绝；随后按thread ID/beforeTurnId成功分叉一次。子文件只有2条本地记录，history_base引用183条/594583字节父段。初次平面读取的“不等价”判定保留，history-resolution.json单独更正：全部原生压缩字段保持，有效7项，比压缩刚结束多一条正常执行事实。没有第二分叉；进程退出、0新增响应、原工作区和父文件不变。未验证实际提交模型的请求等价。

新native_fork_history独立旁路解析外部登记的单层父前缀，未解析嵌套父历史明确拒绝。发现原native_evidence.state会修改传入压缩列表，重复读取真实归档61→116、66→125；新native_history_projection先旁路A/B，原首次结果相同且重复稳定后，接回原state入口。最终28项相关检查通过、4份真实归档与旧canonical-state一致；新分叉审计失败由该代码副作用触发并已离线纠正，未重跑原生调用。

当前141活动Python文件，源清单在native-transport验证目录。不能把该工具缺陷当旧9.4%输出差异的原因，旧用量/质量结论未改。下一步先将分页继承历史、执行身份和新增用量边界纳入实验准入，再考虑小规模原生重复对照；现有phase不能直接当已支持分叉。主目标不变，不拿基础验证冒称长期收益。

## 最新继续：公开验收旁路与方案复核

[本轮报告](../reviews/2026-10-23-public-contract-and-design-review.md)。新增native_public_checks独立模块，发布完整测试原文、全部阶段请求和人工边界映射；父代理保留摘要，实际任务Python执行指定范围并绑定实际验收副本。未来须在首次共享源任务前发布且两臂共同可见；不是隐藏测试机制，未知未来要求研究仍未完成。7项针对性检查通过，旧grade不改，不重复全回归。

离线校准`D:/agent-task-runs/wsc-public-contract-calibration-20261023-v1/result.json`：B13/13，C大整数方法4个子用例报错，其余12方法通过；使用相同合同、原Python3.11.9/4300位限制。原产物完整清单未变，0模型调用。初次驱动在两个回执完成后误分类unittest error而断言失败，错误保留；finalize.py只结算现有回执，未重跑。不能把事后校准改写成原预登记成绩。

真实包审计确认第二边界携带第一轮完整状态文本，12896→27427序列化字节；native添加消息元数据，比较域为type/role/phase/content。新信息与历史证据均在增量中，不将全部增长称为冗余或因果故障。当前原消息策略保留为保真对照，尚无依据确定为长期收益方案；下一步评估语义摘要与可核查证据的职责，不重复Cursor/选材失败题，不靠补字段或换措辞启动新付费比较。

当前活动137个Python文件（上一轮135，本轮仅新增模块和对应测试），新回执及版本另存public-contract验证目录。核心src与主python均未改。没有新付费研究登记或模型进程；当前无等待中的模型句柄。

## 最新结果：两次边界比较已结束，C资格已更正

[完整报告](../reviews/2026-10-23-strict-jsonl-pair-results.md)：`D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1/reviewed-result.json`状态completed_comparison_with_C_contract_gap。共享源5、两臂8/11具名检查通过，但按原要求补审5000位正负整数发现C因默认4300位限制拒绝、B准确保留。原C资格判断过宽，原review保持、更正另存`C/post-review-correction.json`。两臂final-workspace原样保留，活动workspace为B终态，不重跑、不代修C后补记成功。

C 25响应/1,080,850 tokens，B含两次原生压缩32响应/1,339,809；C总量-19.33%，主要是缓存输入减少，非缓存输入仅-0.64%，输出+9.44%、推理+32.50%，阶段耗时+10.08%。共享源15响应/526,494，总72响应/2,947,153，完整用量已归档。金额未知，不能宣称同等质量或经济胜出。B实际读取完整验收器，非盲测；大整数实现先于读取验收器，不能归因于验收泄露。

公开行动证据在原实验`postrun-contract-audit/trajectory-and-receipts.json`。C有限数阶段一次补丁上下文错、两次脚本语法错，正确源码之前已读到；这些是额外工作线索，不是压缩因果证明。Cursor/版本盘点/旧理由问答已有结果，不重复。

## 最新修复：回执身份明确化旁路

[修复报告](../reviews/2026-10-23-receipt-identity-fix.md)：新模块native_receipt_identity，显式`bind_receipt_file=True`保留receipt_sha256旧JSON值含义，增加计算域及同次读取绑定的文件字节哈希；现有默认入口不变。8项新检查与38项相关兼容检查通过，原B两份真实回执离线对照通过，0新增模型响应。当前活动135个Python文件；原付费实验使用133文件，版本为`20261023-strict-jsonl-pair-v1-delta.zip`，不能说它跑过当前135文件。

验收覆盖已逐条核对：[覆盖审查](../reviews/2026-10-23-strict-jsonl-acceptance-audit.md)。下一研究先处理书面需求与运行时边界的验收映射、未来阶段测试提前可见的问题；新登记才显式启用回执旁路且两臂一致。没有新付费任务登记，不继续旧实验追成功。旁路解决已确认的证据表达歧义，尚未证明模型收益；C大整数遗漏不能靠增加需求字段直接推定治本。

## 最新继续结果：第二次检查点旁路已验证

[连续检查点报告](../reviews/2026-10-23-successor-checkpoint.md)：新增 `native_successor_checkpoint.py`，将零推理宿主来源与当前回合结算分离，绑定实际前次发布包并校验其祖先冷档；旧首轮入口合同不变、核心src未改。19项针对性检查通过。当前活动130个Python文件，不能继续引用下文128文件作为当前完整清单。

真实0推理演练 `D:/agent-task-runs/wsc-successor-host-publication-20261023-v1`，会话99396退出0：来源为已有C最终交接的append_only_turn归档，旧入口先复现scope拒绝，新旁路实际第二次发布/导入21条成功，保留19条任务消息原值，校验119个冷依赖文件，渲染33475字节。源线程、工作区与源码pins未变，实际响应0；不是二次压缩后的任务质量或收益证明。第一次13144与第二次33475来自不同阶段材料，不能当压缩率比较；原消息政策仍随历史增长。

后续新对比需源首次调用前留存并核验B、C1、C2实际线程。初次C导入用PendingHostCheckpoint；C1续接后的第二次导入用PendingSuccessorCheckpoint，origin来自C1最初零推理宿主观察，parent_digest来自C1实际host-publication回执，parent_path是对应已归档package.json。新任务和分阶段验收尚未登记，不启动模糊范围付费实验；原bounded-command C与B停止记录不重跑。

## 最新继续结果：B零推理准入停止

[当前报告](../reviews/2026-10-23-status-and-B-admission.md)覆盖下文较旧的“下一步启动B”。正式B目录为 `D:/agent-task-runs/wsc-bounded-command-20261023-v2/B`，已登记后停止，不能原地重启。新原生启动材料增加recommended_plugins块，其他宿主字段及启动消息相同；新增实验模型响应0。源线程rollout和C工作区哈希均未变，尚未归档搬迁C或恢复源代码；C仍位于原workspace。

先前简化探针少了插件发现步骤；补齐后探针一度完全相同，但实际正式B又变化，不能用较早探针的相等覆盖正式准入失败。具体原生推荐清单加载原因未证实。证据 `validation/bounded-B-20261023/diagnosis.json`，真实差异host-diff.txt；现有NativeGroupAdmission对这组归档正确拒绝。当前128活动源码仍与最终47项检查清单一致，未重复测试。

留存流程零推理验证现已通过：`D:/agent-task-runs/wsc-retained-host-publication-20261023-v1/result.json`，会话47814退出0；同进程配对宿主相同，保留C后复用PendingHostCheckpoint实际发布/导入9条成功，两线程归档均0响应，工作区和源线程不变；不需要新增核心模块。脚本 `validation/bounded-B-20261023/retained_rehearsal.py`。正式新任务需用源阶段execution_fact作两线程初始共同控制，源调用直接复用，避免额外assistant观察进入源bootstrap边界；当前演练没有执行付费源任务或原生压缩。

后续将已验证的留存生命周期用于新多次状态变化任务，在首次付费源任务前配对准入，实际阶段配置及用量仍逐次校验。不要继续对旧C反复新开B探针碰相等，不改原生提示或插件配置凑条件；本次C资格保留，整体收益与长期目标仍未证明。

## 目标与授权

最终标准是[桌面目标](<C:/Users/48522/Desktop/`12.md>)中的长期正确续接、适当补证及值得的总体成本，并与未改的原生 Codex 比较。基础记录保真、短视图、具名检查通过均不能替代整体目标。设计基准：`docs/WSC-PLUGGABLE-DESIGN-v1.0.md`；授权已包含先检查再修改、必要测试和有依据的实验，不重复请求同一许可。

用户最新提醒：Cursor 已研究过，不要陷入重复尝试。不能靠补字段、补措辞、反复生成追成功，也不能把历史失败当作永久否决新方案。

## 最新结果：新命令输出限额 C 完整交付

[完整结果](../reviews/2026-10-23-bounded-command-C-results.md)：`D:/agent-task-runs/wsc-bounded-command-20261023-v2/reviewed-result.json`确认本登记范围内C资格成立。源11响应/389.234秒/499237 tokens、C扩展15/332.922/659410、交接3/116.359/192198，全部用量完整；总1350845，C部分851608，金额未知。源4/4、扩展8/8外部验收通过，报告正确区分两个清单与4/8范围，保护文件不变，交接无修改。源与C实际宿主观测逐项相同。一次WSC边界，不是长期或净收益证明；B尚未运行。

预算代码在C结束后另修复“显式压缩没有agent final导致精确1响应上限误中断”，最终47项检查通过（`validation/phase-budget-20261023/final-checks.json`）。C实际旧源码在phase-budget-task-v1增量中，不能把其回执冒称最终源码重跑。下一步登记原生B：归档C终态、同cwd恢复源阶段after.zip，续接原源线程原生压缩，执行同请求和预算。可复用native_pair_workspace.preserve_arm原位逐文件恢复；不要重启C、不要修改其产物追成绩。B的压缩+续接计量和实际宿主配置须独立绑定。

## 本次任务的准备与执行合同

[预算与任务报告](../reviews/2026-10-23-phase-budget-and-command-task.md)、[预登记协议](BOUNDED-COMMAND-STUDY-20261023.md)。活动128文件；新增显式phase_budget，旧合同不变，46项相关检查通过。新登记source/C各24响应/600秒/1500000总token，handoff4/120/400000；包生成0调用、host_messages模式。版本 `versions/20261023-phase-budget-task-v1-delta.zip` 45176字节，ready回执在 `validation/phase-budget-20261023/ready.json`。

真实问题：旧可选命令生成器在子进程结束后才检查stdout限额；有限真实复现及验收器校准已完成。任务在冻结副本新增旁路生成器，先stdout、WSC后新增stderr/双流，最后交接。既有src和AGENTS保护不变，不是重跑旧opaque题。正式目录 `D:/agent-task-runs/wsc-bounded-command-20261023-v2`已结束并取得上述C范围资格。v1仅准备阶段子测试计数不匹配，0模型调用，没有prepared封印，不得启动。任何阶段失败即停止后续，不补跑。

## 最新实施：宿主边界进入真实发布旁路

[阶段报告](../reviews/2026-10-23-progress-report.md)与[实施结果](../reviews/2026-10-23-host-publication.md)。新模块native_host_checkpoint，显式host_messages模式延迟到观察真实目标宿主后再正常stage/导入；默认模式不变、核心src未改。活动124个Python文件，当前28项针对性检查通过，清单绑定回执在 `validation/host-publication-20261023/checks.json`。

真实0推理演练 `D:/agent-task-runs/wsc-host-publication-20261023-v1` 会话47221退出0：同视图旧/新呈现63824→25576字节，任务尾部与原状态字段一致，冷档完整，正常包摘要及实际导入匹配，cursor0/ready、没有HostReceipt、工作区未变。演练后补充“task_started但无回执也拒绝”检查；最终源码通过28项和实际归档回放，实时运行时版本另存ZIP。不得称最终源码重新实时跑过。

候选设计补充 `docs/WSC-HOST-CONTEXT-BOUNDARY-v1.2.md`。下一步新任务/预算合同与完整C资格；不重跑旧opaque、不扩大旧预算。历史观察—修改—新状态关系仍待处理，没有净token/模型质量或B/C收益结论。

## 最新补充：原会话行动理由诊断

[诊断与原文核对](../reviews/2026-10-23-action-rationale-diagnostic.md)：按用户建议向原 C 追加一次只读问答，未继续任务。模型能识别旧验收范围与新 opaque 要求；其所称旧 commentary/现代码不一致，经原轨迹核对实为修复前后状态。原消息热层保留旧定位、补丁细节在冷档，是可继续核查的状态时间关系线索，非已证明的压缩故障或额外输出原因。诊断1响应/89.5秒，完整78328 tokens；0任务命令、0修改，旧回执/历史前缀未变。原回答、逐项核对与回执在 `D:/agent-task-runs/wsc-action-rationale-20261023-v3`，会话60640已退出0。前两次零调用准入故障留档，不重跑旧任务。

## 最新机制研究：宿主上下文边界，0新增模型响应

[边界证据](../reviews/2026-10-23-host-context-boundary.md)与[候选设计v1.1](../../docs/WSC-HOST-CONTEXT-BOUNDARY-v1.1.md)是最新继续点。已确认旧检查点把4条原生启动材料再次注入新宿主；3条完全重复，1条记忆/技能说明已变化。不能把旧宿主说明与任务消息混为一谈，也不能据此断言这是以前输出增加的原因。

真实归档反事实投影保留任务尾部与全部冷证据，只将已绑定旧宿主前缀改为历史入口：items 63836→25596字节（-59.90%，非token/总体上下文收益）。只读原生演练因用户环境权限内容不同而正确拒绝；匹配原实验配置的演练实际导入并持久匹配，均0模型响应、工作区未变。两个目录分别为 `D:/agent-task-runs/wsc-host-context-20261023-transport` 和 `...-transport-matched`，会话9417/38078均退出0。原source/当前host都由真实准入与归档绑定，不按角色或文本相似猜测。

该历史研究阶段仅新增验证脚本和设计文档，当时122源码未变，证据在 `validation/host-context-20261023/delivery.json`，版本 `versions/20261023-host-context-boundary-v1.1.zip`。目前已接入上述旁路，尚无C/B资格。未来任务预算必须在开始前制定；现有phase硬编码10与旧登记一致，不能借此延长旧运行或宣称此前已经完成。

## 最近一次实际模型运行

[取消额外选材生成的候选与结果](../reviews/2026-10-23-message-checkpoint.md) 是当前主入口。

- 原消息检查点复用全部 message 与生产者 observation，工具/opaque 明细留在完整冷档；无二次选材模型、无新理解重写。仅 experiments 旁路，默认 generated 未变。
- 新模块 `experiments/native_message_checkpoint.py` 复用现有 prepare/stage。失败 source-plan 模块与测试已从活动树撤下，完整保留于 `versions/20261023-source-plan-ready-v2.zip`，没有修schema补跑。
- 当前122个 src/tests/experiments Python文件，相关17项检查通过。回执 `validation/message-checkpoint-20261023/delivery.json`；版本 `versions/20261023-message-checkpoint-v1.zip`（205991字节，SHA-256 `6a7e941e59a353a799b6639d7501dab664281d239784a24ffb3648c839f6120a`）。不是全项目或长期收益证明。

唯一真实新运行：`D:/agent-task-runs/wsc-message-checkpoint-20261023-v1`，工具会话34355已退出0。

- 检查点61来源/12热来源，视图131756字节、呈现63836字节，生成调用0；实际原生导入和冷档已核验。
- C扩展阶段10响应/172.141秒触及预登记响应上限；无final、交接或B。已知568135 tokens（输入554789、缓存499328、输出13346/推理9923），完整使用量未知。10份已知回执与归档一致，不能把known写成complete。
- 实际改动3文件：core.py、view_budget.py、test_generation_feasibility.py。随后独立副本外部7/7；现有三测试文件21/22，一处新测试来源数量断言4但实际3。没有代修产物，离线通过不补记原生完成。
- 模型正确识别已有修复及新opaque义务；尚无同期B，不能把中断归因于上下文策略或断言净收益。详见运行根 `evidence-review.json`。

实际任务目录仍为 `D:/agent-task-runs/wsc-control-continuation-20261023-v1/workspace`，**现在已经是这次中断后的修改状态**。不得当作最初冻结起点、不得重启旧registration。原起点在原研究source_task/after.zip以及新研究frozen-workspace；本次产物在新研究expanded_task/after.zip。主仓库 `python/` 有大量其他修改，不触碰/重置它。

## 不重复的已知研究

| 研究 | 已有结论与证据 | 后续约束 |
| --- | --- | --- |
| Cursor参考、本机WSC版本盘点 | `reviews/2026-10-23-cursor-context-reference.md`、`2026-10-23-source-audit.md` | 已有冷档/精确引用，不重复造系统或再全盘扫描 |
| 同稳定工作区手选B/C | `experiments/NATIVE-STABLE-CARRIER-20261023.md`；旧题18/18，总tokens-18.35%，输出增加 | 手选/单任务/固定顺序，不能作当前自动资格 |
| 自动span JSONL续接 | `reviews/2026-10-23-generation-boundary-and-cost.md`；旧题18/18，生成+执行634791 tokens | 无同期B，不重复原题挑结果 |
| full/frontier生成 | `reviews/2026-10-23-frontier-generation-results.md` | bootstrap不同、错误哈希，不能宣称因果收益 |
| 紧凑引用schema、word边界 | `reviews/2026-10-23-span-schema.md`、`2026-10-23-span-boundary.md` | 前者来源失败；后者改善精确值但没有续接收益，不重跑 |
| 中断恢复span | `reviews/2026-10-23-interrupted-recovery.md`；118573 tokens，366879字节超262144 | 父来源全部模型明确完整选择，不可自动删后冒称成功 |
| source-plan | `reviews/2026-10-23-source-plan.md`；120060 tokens，空span schema/编译不一致 | 已封存撤下，不立即修schema再生成 |
| 本轮原消息检查点 | 最新报告与上述实际结果 | 没有合格C，不能进入B/C或延长旧运行上限 |

原始任务取得中断的历史514295已知tokens完整性仍未知；旧失败成本保留，与新增使用量分列。

## 下一步边界

已验证“固定额外选材生成不是检查点导出的必需条件”，没有验证“不生成就能更经济地完成长期任务”。不在本轮已中断样本上补跑到成功。下一研究单元先明确新任务/连续变化及原生可比评价能提供的独立信息，不能再围绕选材格式修补；不得拿本轮外部7/7代替C完整交付资格。

长期仍缺：多次压缩和变化后的完整交付、必要与过度补证的区分、同源同期原生比较、包含失败与维护的总体成本。保持模型自决与中性事实呈现，不靠给引擎添加导演式提示纠偏。

原生环境：固定共享Python `D:/agent-task-runs/wsc-tools/python-3.11.9-stdlib/python.exe`。相同沙箱command/exec预检在模型前执行；不改原生配置、提示、权限、ACL或PATH。运行使用登记的原生二进制、gpt-6-luna/max；实际pins与bootstrap仍需逐次核验，旧资格不能跨源码/来源/配置漂移使用。

## 历史保存

旧长交接文档完整存于 `versions/20261023-handoff-history.zip`，内含同名Markdown；原文SHA-256 `1c14cda42640c1a917f99087b0df17b99fa334c96fb0234291c87b09dae351b3`。其旧“当前/完成”措辞均为历史状态，不覆盖本文。查具体故障优先打开上述报告，避免每次加载全部历史。

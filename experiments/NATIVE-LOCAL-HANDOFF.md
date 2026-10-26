# 独立 WSC 本地续接：当前交接

更新：2026-10-26。长期目标尚未达成，当前正在运行固定S2交接状态的三组B/C续接对照，没有修改目标工具状态。当前代理直接完成，不使用子代理。用户要求每次报告明确下一步。以下历史段落不覆盖本节最新状态。

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

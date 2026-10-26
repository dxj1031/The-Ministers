# 历史改动与修复追踪

补录日期：2026-10-25（America/Los_Angeles）。本次已执行 `git fetch origin`，依据远端 Git 提交、实际差异和仓库原有文档整理。

## 范围和证据等级

- 可追溯的最早提交为 2026-08-11 的 [`27656a5`](https://github.com/dxj1031/The-Ministers/commit/27656a5f9dfd6c39a23494cfdd4d545524e0c21d)。该提交已经包含前端原型和后端，当前仓库没有更早的原型制作过程，不能据此补写不存在的修复步骤。
- 本次核对基线：部署分支 `origin/codex/deploy-render-free`，截至 `cf92e4b`，共 56 次提交；`origin/main` 截至 `9e5f40b`，共 17 次提交。部署分支比 main 多 39 次提交。下表冻结在这次补录之前，不包含本次文档提交本身。
- **代码证据**：Git 差异可确认改了什么；增加测试可确认测试代码存在，不能证明当时测试实际运行并通过。
- **历史验证记载**：原提交说明或旧文档记载的测试、部署、统计，只作为当时的记录保留，本次没有重新执行所有历史版本。
- **线上验证**：只有存在明确发布或浏览器验收记录的项目才记为已验证；代码提交、静态快照更新和默认分支合并均不自动等于线上功能可用。
- GitHub 网页抓取可能滞后；分支计数以本次 fetch 后的 Git 对象为准。日期按提交作者记录的时间；这些提交使用 -07:00，与当日洛杉矶时区一致。

## 早期关键修复

| 日期 | 问题／改动 | 代码证据 | 验证边界 |
| --- | --- | --- | --- |
| 2026-08-11 | 初次入库：后端、辩论引擎、可观测控制台、真实前后端连接 | [`27656a5`](https://github.com/dxj1031/The-Ministers/commit/27656a5f9dfd6c39a23494cfdd4d545524e0c21d) | 是当前仓库起点，不能等同于线上已跑通 |
| 2026-08-11 | 增加 Pages 静态快照部署和跨仓库同步；静态站不再探测不存在的 API，避免 404 | [`d75b339`](https://github.com/dxj1031/The-Ministers/commit/d75b339bcd5ddbbba9375b06ef98f8c524b03901)、[`fc1a666`](https://github.com/dxj1031/The-Ministers/commit/fc1a66626f4fd9a3789e276839a35f65f73772e1) | 当时是静态展示方案；后来的 Render 动态服务另有发布记录 |
| 2026-08-11 | 桌面适配与实时实录面板 | [`1b2ea52`](https://github.com/dxj1031/The-Ministers/commit/1b2ea527a02e303072af8cf288cc33141aeac505) | 当时采用手机画框缩放；10月25日后被全流程响应式布局继续调整 |
| 2026-08-11 | 蝴蝶文库检索；防御异常模型 JSON；禁止模型擅自替换引擎选定的辩论双方 | [`658e1fc`](https://github.com/dxj1031/The-Ministers/commit/658e1fc163ca7d5a671370f79882770611f9abdf) | 差异中可见 `tests/test_court.py` 和 `tests/test_library.py` 的回归用例；未重跑历史版本 |
| 2026-08-11 | 静态快照补导出检索记录，供控制台查看 | [`8d0125c`](https://github.com/dxj1031/The-Ministers/commit/8d0125c0ce7e1bd59794cb2819e4c0ee99dbd0e6) | 快照导出能力，不是新增公网后端 |
| 2026-10-09 | 手机控制台由整页横滚改为表格内部滚动，修复375px下网格最小宽度撑开页面 | [`c526ba8`](https://github.com/dxj1031/The-Ministers/commit/c526ba84c54646081d5cff75a04c302c32059bcb)、[`3d6f5ab`](https://github.com/dxj1031/The-Ministers/commit/3d6f5abc9ddb79e428d4cdef8cf06a391280392b) | 已核对 CSS 差异，本次未对历史页面截图验收 |
| 2026-10-09 | 固定题集、机械评分、人设评审、评估对比；无人设评审时记空值 | [`fe6afd9`](https://github.com/dxj1031/The-Ministers/commit/fe6afd9ac740129921e96fc0037a602ec05e53a8)、[`c4ba356`](https://github.com/dxj1031/The-Ministers/commit/c4ba35663f139e1c577290296a6d1f512e1eba60) | 有评估测试代码；离线评分回归不能证明真实模型人设质量 |
| 2026-10-09 | 修复延迟下降被错误标为退步；延迟差值显示毫秒 | [`b1c617a`](https://github.com/dxj1031/The-Ministers/commit/b1c617ae955caf1fb251a5d437819090a993e139) | 核对评分方向代码及新增断言 |
| 2026-10-23 | 迎合率、应声角色、带署名判词与异议、罢免应声 | [`040ff3a`](https://github.com/dxj1031/The-Ministers/commit/040ff3a1d535b436a04110b0bf65d0d99f4ec57b)、[`4c8075a`](https://github.com/dxj1031/The-Ministers/commit/4c8075a4d4857df908367aaaaabb4d1577646303)、[`5030486`](https://github.com/dxj1031/The-Ministers/commit/5030486765464e863d04976702187c38cc4aa653)、[`7955b8d`](https://github.com/dxj1031/The-Ministers/commit/7955b8dfd6c3b35afe1094e12c87b46b713e0bf4) | 后续 `dd537eb` 将应声改为实际参辩，早期“只在结尾出现”不能视为当前规则 |
| 2026-10-23 | 用户档案追加写、拾荒整理四项心事、用户自行修改；开场倾向和朝堂镜 | [`be1627b`](https://github.com/dxj1031/The-Ministers/commit/be1627b77515c3669922e69bb129d61b0aca2174)、[`ee67fe7`](https://github.com/dxj1031/The-Ministers/commit/ee67fe70190d7d7dd3864ff02dfabce342aaad2a)、[`58b1cac`](https://github.com/dxj1031/The-Ministers/commit/58b1cac398eced37ea81e1afb8ac27ad4edb536e)、[`a2ee049`](https://github.com/dxj1031/The-Ministers/commit/a2ee049d4476c1968b0152c70723c26897fad9e6)、[`2740b87`](https://github.com/dxj1031/The-Ministers/commit/2740b8732d6cc44b955548e2608dfd09475150ec) | 记录机制已入代码；不是档案内容真实性的保证 |
| 2026-10-23 | 修档案去重让稳定性指标失真、模型失败复述旧档、旧档默认照抄；保留用户钉选字段的作者归属 | [`8652283`](https://github.com/dxj1031/The-Ministers/commit/86522831b192174034ce3de5372bc6c5a736919c) | 已核对 `read_user` 差异；后续会话隔离继续由 `dd537eb` 调整 |
| 2026-10-23 | 御笔收藏进库；修真实数据渲染 `liveView` 缺少 `t` 参数引发的 ReferenceError | [`6e02134`](https://github.com/dxj1031/The-Ministers/commit/6e02134fa6287a5c9dada1a3391dd380258c9b81)、[`d91e40b`](https://github.com/dxj1031/The-Ministers/commit/d91e40b551b304c0de01843baab66291377baf21) | 已核对参数传递及收藏界面差异；不能用离线演示替代真实流程验收 |
| 2026-10-23 | 导出快照过滤未完成评估和100%兜底的离线回归；总览采用同样过滤规则 | [`a93e35a`](https://github.com/dxj1031/The-Ministers/commit/a93e35abbe7435d9ea6b5fb69c48c18267e1728a) | 这只是展示口径修正，不代表模型本身质量改善。原提交报告英文人设分为0，明确仍待调查 |
| 2026-10-25 | Render免费部署准备、访问口令、桌面启动器、交互与响应式界面整合 | [`eb169de`](https://github.com/dxj1031/The-Ministers/commit/eb169defd15f4a10e6570003c4ae57c24ef7ef8c) | 单次提交包含大量此前本地工作，无法从该提交再还原每个小步骤；部署准备不等于上线成功 |
| 2026-10-25 | 本地优先识别5060 Ti；补声明文库依赖NumPy | [`c67c209`](https://github.com/dxj1031/The-Ministers/commit/c67c2090e61b89dec4354713be4489bb8feb9167)、[`03cc0b1`](https://github.com/dxj1031/The-Ministers/commit/03cc0b18c17c3e925c14e575ad25a56800a297b6) | 本地显卡调整不代表云端使用该显卡；依赖提交本身不证明部署成功 |
| 2026-10-25 | Gemini单对象数组及直接名册兼容；解析／结构兜底如实显示 | [`2f7cdfd`](https://github.com/dxj1031/The-Ministers/commit/2f7cdfd1d462a473ba7b3004346a281be5c354c0) | 核对标准化与fallback记录代码，新增 `tests/test_model_compat.py` |

后续联网资料、Tavily、暂停、下载、返回、裁决和语言默认值的细节与真实线上验收，继续见 [线上修复记录](repair-log.md)。

## 全部提交索引

“main”表示此次核对时已包含在默认分支；“部署分支”表示仅包含在 `codex/deploy-render-free`。文件清单取自每次提交的实际差异。测试栏只列变更的测试文件，**不表示已经运行**。快照、文档、功能和缺陷修复均保留，避免只挑看起来成功的记录。

| 日期 | 提交 | 分支范围 | 原提交说明 | 主要变更文件 | 变更的测试 |
| --- | --- | --- | --- | --- | --- |
| 2026-08-11 | [`27656a5`](https://github.com/dxj1031/The-Ministers/commit/27656a5f9dfd6c39a23494cfdd4d545524e0c21d) | main | Add backend, debate engine, observability console and live frontend wiring | `.claude/launch.json`<br>`.env.example`<br>`.gitignore`<br>`README.md`<br>`app/back/core/llm.py`<br>另24个文件（见提交） | `tests/test_court.py`<br>`tests/test_store.py` |
| 2026-08-11 | [`d75b339`](https://github.com/dxj1031/The-Ministers/commit/d75b339bcd5ddbbba9375b06ef98f8c524b03901) | main | Add Pages deploy: static snapshot mode and a sync script for personal-page | `app/front/The Court.dc.html`<br>`index.html`<br>`tools/deploy_pages.py` | 无 |
| 2026-08-11 | [`fc1a666`](https://github.com/dxj1031/The-Ministers/commit/fc1a66626f4fd9a3789e276839a35f65f73772e1) | main | Probe the API only on localhost so static hosting logs no 404 | `app/front/The Court.dc.html`<br>`index.html` | 无 |
| 2026-08-11 | [`1b2ea52`](https://github.com/dxj1031/The-Ministers/commit/1b2ea527a02e303072af8cf288cc33141aeac505) | main | Adapt the court to desktop and add a live transcript panel | `app/front/The Court.dc.html` | 无 |
| 2026-08-11 | [`a5739d3`](https://github.com/dxj1031/The-Ministers/commit/a5739d332735f4b417945ab2e0b6875a90c09b43) | main | Refresh snapshot: 8 sessions, 46 calls | `snapshot.json` | 无 |
| 2026-08-11 | [`4da363b`](https://github.com/dxj1031/The-Ministers/commit/4da363bdfa02439996e1008e395990e622b67fa0) | main | Prepare for a public repo | `.claude/launch.json`<br>`.gitignore`<br>`README.md`<br>`graphify-out/.graphify_analysis.json`<br>`graphify-out/.graphify_labels.json`<br>另9个文件（见提交） | 无 |
| 2026-08-11 | [`658e1fc`](https://github.com/dxj1031/The-Ministers/commit/658e1fc163ca7d5a671370f79882770611f9abdf) | main | Add the Cocoon Library: retrieval that measures confirmation bias | `README.md`<br>`app/back/core/schema.sql`<br>`app/back/core/store.py`<br>`app/back/main.py`<br>`app/back/services/court.py`<br>另2个文件（见提交） | `tests/test_court.py`<br>`tests/test_library.py` |
| 2026-08-11 | [`d966ac7`](https://github.com/dxj1031/The-Ministers/commit/d966ac7010d7e5251fb9619822b4eb917320b001) | main | Refresh snapshot with retrieval data | `snapshot.json` | 无 |
| 2026-08-11 | [`8d0125c`](https://github.com/dxj1031/The-Ministers/commit/8d0125c0ce7e1bd59794cb2819e4c0ee99dbd0e6) | main | Export retrievals in the snapshot so the static console shows them too | `snapshot.json`<br>`tools/export_snapshot.py` | 无 |
| 2026-10-09 | [`e1c0438`](https://github.com/dxj1031/The-Ministers/commit/e1c0438b465bd04f64d99306e1b866b2869b1bb0) | main | Point the console source link at this repo and note where the deploy lives | `README.md`<br>`index.html` | 无 |
| 2026-10-09 | [`c526ba8`](https://github.com/dxj1031/The-Ministers/commit/c526ba84c54646081d5cff75a04c302c32059bcb) | main | Console: let the data tables scroll instead of the whole page on phones | `index.html` | 无 |
| 2026-10-09 | [`3d6f5ab`](https://github.com/dxj1031/The-Ministers/commit/3d6f5abc9ddb79e428d4cdef8cf06a391280392b) | main | Console: no horizontal page scroll at 375px (1fr implies a min of auto) | `index.html` | 无 |
| 2026-10-09 | [`fe6afd9`](https://github.com/dxj1031/The-Ministers/commit/fe6afd9ac740129921e96fc0037a602ec05e53a8) | main | Add the evaluation harness: a fixed topic set and reproducible scorers | `app/back/core/schema.sql`<br>`app/back/core/store.py`<br>`app/back/evaluation/cases.py`<br>`app/back/evaluation/runner.py`<br>`app/back/evaluation/scorers.py`<br>另2个文件（见提交） | `tests/test_eval.py` |
| 2026-10-09 | [`c4ba356`](https://github.com/dxj1031/The-Ministers/commit/c4ba35663f139e1c577290296a6d1f512e1eba60) | main | Show evaluation runs in the console, with the delta against the previous run | `README.md`<br>`index.html` | 无 |
| 2026-10-09 | [`b1c617a`](https://github.com/dxj1031/The-Ministers/commit/b1c617ae955caf1fb251a5d437819090a993e139) | main | Count falling latency as an improvement in the eval report | `app/back/evaluation/runner.py` | `tests/test_eval.py` |
| 2026-10-23 | [`99ab75c`](https://github.com/dxj1031/The-Ministers/commit/99ab75cbddb791bd6caa948a6a8b0ad87bb00480) | main | Refresh the snapshot: 8 sessions, 226 calls, 2 eval runs | `snapshot.json` | 无 |
| 2026-10-23 | [`9e5f40b`](https://github.com/dxj1031/The-Ministers/commit/9e5f40b8a255542a4058fc01f34b76e3e8129dfb) | main | Keep the local study notes out of the public repo | `.gitignore` | 无 |
| 2026-10-23 | [`040ff3a`](https://github.com/dxj1031/The-Ministers/commit/040ff3a1d535b436a04110b0bf65d0d99f4ec57b) | 部署分支 | 量出迎合：终局立场与皇帝倾向同向的大臣比例 | `app/back/evaluation/runner.py`<br>`app/back/evaluation/scorers.py`<br>`index.html` | `tests/test_eval.py` |
| 2026-10-23 | [`4c8075a`](https://github.com/dxj1031/The-Ministers/commit/4c8075a4d4857df908367aaaaabb4d1577646303) | 部署分支 | 把迎合收进一个角色：第十二位大臣「应声」 | `app/back/ministers/roster.py`<br>`app/back/services/court.py`<br>`app/front/The Court.dc.html` | `tests/test_court.py` |
| 2026-10-23 | [`5030486`](https://github.com/dxj1031/The-Ministers/commit/5030486765464e863d04976702187c38cc4aa653) | 部署分支 | 裁决双句：恭维有署名，异议留在场上 | `app/back/evaluation/scorers.py`<br>`app/back/services/court.py`<br>`app/front/The Court.dc.html` | `tests/test_court.py`<br>`tests/test_eval.py` |
| 2026-10-23 | [`88ff7f2`](https://github.com/dxj1031/The-Ministers/commit/88ff7f27cb3f2bd8afecb4885aa373f0efd88552) | 部署分支 | 写下设计文档：三个目的，各自的机制和验收指标 | `README.md`<br>`docs/system_design_v0.md` | 无 |
| 2026-10-23 | [`be1627b`](https://github.com/dxj1031/The-Ministers/commit/be1627b77515c3669922e69bb129d61b0aca2174) | 部署分支 | 用户档案落库：user_read 追加写，按字段取最新 | `app/back/core/schema.sql`<br>`app/back/core/store.py` | 无 |
| 2026-10-23 | [`ee67fe7`](https://github.com/dxj1031/The-Ministers/commit/ee67fe70190d7d7dd3864ff02dfabce342aaad2a) | 部署分支 | 拾荒当档案官：追踪多轮输入，只投喂给五位大臣 | `app/back/services/court.py` | `tests/test_court.py` |
| 2026-10-23 | [`58b1cac`](https://github.com/dxj1031/The-Ministers/commit/58b1cac398eced37ea81e1afb8ac27ad4edb536e) | 部署分支 | 朕的心事：桌面右栏常驻，四项都能改 | `app/back/main.py`<br>`app/front/The Court.dc.html` | 无 |
| 2026-10-23 | [`0d3076b`](https://github.com/dxj1031/The-Ministers/commit/0d3076bad845a2097b9d9aa4682ad4cedb6318d1) | 部署分支 | 文档跟上目的 2：档案官改写了 M2，README 补上这一节 | `README.md`<br>`docs/system_design_v0.md` | 无 |
| 2026-10-23 | [`a2ee049`](https://github.com/dxj1031/The-Ministers/commit/a2ee049d4476c1968b0152c70723c26897fad9e6) | 部署分支 | 朝堂镜：开场倾向落库，裁决后算出谁把你推过去的 | `app/back/core/schema.sql`<br>`app/back/core/store.py`<br>`app/back/main.py`<br>`app/back/services/court.py` | `tests/test_court.py` |
| 2026-10-23 | [`2740b87`](https://github.com/dxj1031/The-Ministers/commit/2740b8732d6cc44b955548e2608dfd09475150ec) | 部署分支 | 奏章屏加开场倾向滑条，裁决屏加朝堂镜三行 | `app/front/The Court.dc.html` | 无 |
| 2026-10-23 | [`445abd7`](https://github.com/dxj1031/The-Ministers/commit/445abd701bc68d281536fbf10993b509355db0be) | 部署分支 | 文档跟上目的 3：设计文档标为已实现，progress 收尾 | `docs/progress.md`<br>`docs/system_design_v0.md` | 无 |
| 2026-10-23 | [`9867998`](https://github.com/dxj1031/The-Ministers/commit/986799815c4e06305c1d73e3c76d81c735a53e1c) | 部署分支 | 量拾荒：抽出几项，以及它是不是每次都推倒重来 | `app/back/core/store.py`<br>`app/back/evaluation/runner.py`<br>`app/back/evaluation/scorers.py`<br>`app/back/main.py`<br>`index.html` | `tests/test_eval.py` |
| 2026-10-23 | [`8652283`](https://github.com/dxj1031/The-Ministers/commit/86522831b192174034ce3de5372bc6c5a736919c) | 部署分支 | 修拾荒的三处毛病，都是上一个 commit 的指标抓出来的 | `app/back/services/court.py` | 无 |
| 2026-10-23 | [`53a3b33`](https://github.com/dxj1031/The-Ministers/commit/53a3b33ca70c4593752d1f88abdbda0aa09b7414) | 部署分支 | 文档跟上：机械层指标已实现，以及它抓到了什么 | `README.md`<br>`docs/progress.md`<br>`docs/system_design_v0.md` | 无 |
| 2026-10-23 | [`7955b8d`](https://github.com/dxj1031/The-Ministers/commit/7955b8dfd6c3b35afe1094e12c87b46b713e0bf4) | 部署分支 | 罢免应声：赶走谀臣，判词就得自己扛 | `app/back/core/schema.sql`<br>`app/back/core/store.py`<br>`app/back/services/court.py` | `tests/test_court.py` |
| 2026-10-23 | [`4d62c32`](https://github.com/dxj1031/The-Ministers/commit/4d62c32bbbb38715587f4861546d20d61d372a5f) | 部署分支 | 应声的出场方式：名册里不编号，朝堂上不说话 | `app/front/The Court.dc.html` | 无 |
| 2026-10-23 | [`309bbb4`](https://github.com/dxj1031/The-Ministers/commit/309bbb44f5f161e9f65ee78c84473ef428b55463) | 部署分支 | 文档跟上：M1.4 已实现，应声收尾 | `README.md`<br>`docs/progress.md`<br>`docs/system_design_v0.md` | 无 |
| 2026-10-23 | [`6e02134`](https://github.com/dxj1031/The-Ministers/commit/6e02134fa6287a5c9dada1a3391dd380258c9b81) | 部署分支 | 御笔批注进库，朝堂镜加一条「你总收藏谁」 | `app/back/core/store.py`<br>`app/back/main.py`<br>`app/back/services/court.py` | `tests/test_court.py` |
| 2026-10-23 | [`d91e40b`](https://github.com/dxj1031/The-Ministers/commit/d91e40b551b304c0de01843baab66291377baf21) | 部署分支 | 实录每行加「御笔收藏」，并修掉 liveView 一直缺 t 的崩溃 | `app/front/The Court.dc.html` | 无 |
| 2026-10-23 | [`20edf1b`](https://github.com/dxj1031/The-Ministers/commit/20edf1b8c12e59a073895cbbe546eaa7222fbda5) | 部署分支 | 文档跟上 M3.3，并改掉一句一直是错的话 | `README.md`<br>`docs/progress.md`<br>`docs/system_design_v0.md` | 无 |
| 2026-10-23 | [`a93e35a`](https://github.com/dxj1031/The-Ministers/commit/a93e35abbe7435d9ea6b5fb69c48c18267e1728a) | 部署分支 | 快照只展示真跑：离线回归不进线上 | `app/back/core/store.py`<br>`snapshot.json`<br>`tools/export_snapshot.py` | 无 |
| 2026-10-25 | [`eb169de`](https://github.com/dxj1031/The-Ministers/commit/eb169defd15f4a10e6570003c4ae57c24ef7ef8c) | 部署分支 | Prepare free Render court deployment, Google AI access and desktop launcher | `.env.example`<br>`README.md`<br>`app/back/core/access.py`<br>`app/back/core/schema.sql`<br>`app/back/core/store.py`<br>另9个文件（见提交） | `tests/test_deployment.py`<br>`tests/test_desktop.py`<br>`tests/test_experience.py`<br>`tests/test_frontend.cjs`<br>另1个测试文件 |
| 2026-10-25 | [`c67c209`](https://github.com/dxj1031/The-Ministers/commit/c67c2090e61b89dec4354713be4489bb8feb9167) | 部署分支 | Prefer the connected 5060 Ti for the local desktop court | `README.md`<br>`docs/deploy_online.md`<br>`docs/progress.md`<br>`tools/desktop_court.py`<br>`tools/install_desktop.ps1` | `tests/test_desktop.py` |
| 2026-10-25 | [`03cc0b1`](https://github.com/dxj1031/The-Ministers/commit/03cc0b18c17c3e925c14e575ad25a56800a297b6) | 部署分支 | Declare NumPy required by court library retrieval | `requirements.txt` | 无 |
| 2026-10-25 | [`2f7cdfd`](https://github.com/dxj1031/The-Ministers/commit/2f7cdfd1d462a473ba7b3004346a281be5c354c0) | 部署分支 | Accept Gemini response wrappers and expose parsing fallback accurately | `app/back/core/llm.py`<br>`app/back/services/court.py`<br>`app/front/The Court.dc.html` | `tests/test_model_compat.py` |
| 2026-10-25 | [`dd537eb`](https://github.com/dxj1031/The-Ministers/commit/dd537eb99b1f1ca052a700475d0573b1473f4537) | 部署分支 | Ground minister debates in public sources and give users session control | `.env.example`<br>`README.md`<br>`app/back/core/store.py`<br>`app/back/evaluation/scorers.py`<br>`app/back/main.py`<br>另8个文件（见提交） | `tests/test_court.py`<br>`tests/test_experience.py`<br>`tests/test_frontend.cjs`<br>`tests/test_model_compat.py`<br>另2个测试文件 |
| 2026-10-25 | [`b07e3a8`](https://github.com/dxj1031/The-Ministers/commit/b07e3a83daf08893286d7ffdf1dc73b820fd5257) | 部署分支 | Label public citations correctly in court transcripts | `app/front/The Court.dc.html` | `tests/test_frontend.cjs` |
| 2026-10-25 | [`32f1bad`](https://github.com/dxj1031/The-Ministers/commit/32f1bad6bd1c11fdcca48c67f972dd500b50318f) | 部署分支 | Show reasons and source links inline and shorten speech pauses | `app/front/The Court.dc.html` | `tests/test_frontend.cjs` |
| 2026-10-25 | [`879bb4a`](https://github.com/dxj1031/The-Ministers/commit/879bb4a06cec194530931bc425a909dc28f145f2) | 部署分支 | Use grounded Google research and share cited evidence across ministers | `app/back/core/llm.py`<br>`app/back/services/court.py`<br>`app/back/services/research.py` | `tests/test_research.py` |
| 2026-10-25 | [`5eb12da`](https://github.com/dxj1031/The-Ministers/commit/5eb12da977bff4a7d6df13acbc574580f0972af6) | 部署分支 | Use Gemini Interactions search citations and retry failed research | `app/back/core/llm.py`<br>`app/back/services/court.py`<br>`app/back/services/research.py` | `tests/test_research.py` |
| 2026-10-25 | [`239fa2a`](https://github.com/dxj1031/The-Ministers/commit/239fa2ac3a78359254573db3878d1d63b4814bca) | 部署分支 | Decode grounded Chinese citation spans using UTF-8 byte offsets | `app/back/core/llm.py` | `tests/test_research.py` |
| 2026-10-25 | [`bdafbe1`](https://github.com/dxj1031/The-Ministers/commit/bdafbe1e9f3e26f5bfe1d39052124e5546a6fd82) | 部署分支 | Prioritize Tavily research and stop unsupported hosted debates | `app/back/main.py`<br>`app/back/services/court.py`<br>`app/back/services/research.py`<br>`app/front/The Court.dc.html`<br>`docs/deploy_online.md` | `tests/test_frontend.cjs`<br>`tests/test_research.py` |
| 2026-10-25 | [`4219bfd`](https://github.com/dxj1031/The-Ministers/commit/4219bfdae92b4ccc38878efbc76f2e3e52e31a2f) | 部署分支 | Scope pause to court animations and restore pending record download and resume | `app/front/The Court.dc.html` | `tests/test_frontend.cjs` |
| 2026-10-25 | [`f44fa01`](https://github.com/dxj1031/The-Ministers/commit/f44fa014cc1963af69816f3b59e9a0cbb19bb2be) | 部署分支 | Document repair causes, deployment and online acceptance evidence | `docs/repair-log.md` | 无 |
| 2026-10-25 | [`f512e57`](https://github.com/dxj1031/The-Ministers/commit/f512e57f4a821b05893d9d0caef00223bcc94828) | 部署分支 | Record successful online verdict and both download checks | `docs/repair-log.md` | 无 |
| 2026-10-25 | [`4a9614f`](https://github.com/dxj1031/The-Ministers/commit/4a9614f45c4fd5c9c43724b64544d0f54295ddd0) | 部署分支 | Default court to Chinese and honor entry language parameter | `app/front/The Court.dc.html` | `tests/test_frontend.cjs` |
| 2026-10-25 | [`4b1dc47`](https://github.com/dxj1031/The-Ministers/commit/4b1dc47559b214e3911965c1896151c317dd5fec) | 部署分支 | Record Chinese entry verification and language regression coverage | `docs/repair-log.md` | `tests/test_frontend.cjs` |
| 2026-10-25 | [`f913c74`](https://github.com/dxj1031/The-Ministers/commit/f913c74d5fd76694a692199420b88eeba0fce414) | 部署分支 | Set English as the default court language | `app/front/The Court.dc.html` | `tests/test_frontend.cjs` |
| 2026-10-25 | [`cf92e4b`](https://github.com/dxj1031/The-Ministers/commit/cf92e4b4e0b49099567b5ddfdc849fd4ae215865) | 部署分支 | Document English default deployment and online verification | `docs/repair-log.md` | 无 |

## 原有记录和待确认事项

- [项目进展](progress.md) 和 [系统设计](system_design_v0.md) 保存了10月23日及之后的设计、指标与修复说明；存在“部署中”“后端未上线”等历史时态，应结合提交日期阅读，不应当作最新部署状态。
- 8月11日、10月9日、10月23日的快照更新表示当时导出过运行数据；本次未重新检验快照中的每场讨论或模型调用，不据此推断现在的线上效果。
- 本地旧进展提到 Personal Page 的早期发布提交 `8370388`、`93a12b2`；它们属于另一个仓库，本表不伪造成本仓库提交。两库部署关系见 [线上部署说明](deploy_online.md)。
- 当前默认语言按用户最新要求为英文；之前中文默认的提交属于真实历史，保留记录而不删除。
- 无法从Git恢复未提交的本地修改、未记录的浏览器验收、服务商环境变量变更和部署操作；这些只能依靠当时明确留下的记录，缺失处记为待确认。

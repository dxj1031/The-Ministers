# 免费线上后端部署

采用 Render Free Web Service + Google AI Studio 免费额度。服务同时提供朝堂前端和 API，不创建付费磁盘或数据库。根目录 render.yaml 已写好配置。

## 免费版边界

Render 空闲 15 分钟后休眠，唤醒约需一分钟；SQLite 会在休眠、重启、更新后清空，散朝后可下载记录。用户已选择先按此方案免费跑通。Render 免费 Postgres 创建 30 天后过期，不能作为永久免费存储，本方案没有创建它。

Google AI 的 Gemini 3.5 Flash-Lite 当前列有免费输入和输出额度，实际可用量以账号为准。保持免费项目，不启用付费结算。免费额度的数据可能被服务商用于产品改进，不要输入敏感材料。

## 上线步骤

1. 登录 Render，打开[部署入口](https://render.com/deploy?repo=https://github.com/dxj1031/The-Ministers/tree/codex/deploy-render-free)，确认计划是 Free，未增加收费资源。
2. 在 Google AI Studio 创建免费项目的 API Key，只将它填入 Render 的 MINISTERS_API_KEY。不要提交到仓库。
3. 其他配置已写入：MINISTERS_BASE_URL 为 https://generativelanguage.googleapis.com/v1beta/openai，MINISTERS_MODEL 为 gemini-3.5-flash-lite，数据库位于 /tmp/ministers/ministers.db。访问口令 MINISTERS_ACCESS_KEY 由 Render 自动生成，与模型密钥不同。
4. 部署后检查 /api/health，再打开 /front/The%20Court.dc.html。首次呈递奏章时输入访问口令，再重新呈递。
5. 实测模型发言、暂停、词条增删、猫皇插话、裁决和下载。健康检查成功不代表模型可用。

缺访问口令、缺模型密钥或模型仍指向 localhost 时，后端拒绝在 Render 启动。当前访问控制是私人朝堂的共享口令，不是多人账号系统；共享口令的人可见同一份记录。

## 保留原网址

后端实测成功后，设置完整朝堂页面地址再同步 Pages：

```powershell
$env:MINISTERS_APP_URL = 'https://你的服务.onrender.com/front/The%20Court.dc.html'
python tools/deploy_pages.py
```

检查并仅提交 personal-page 中 ministers/index.html 的改动。原 https://dxj1031.github.io/personal-page/ministers/ 将跳转到验证后的 Render 页面，前后端同站，避免跨站 Cookie 问题。后续同步会保留该入口；显式设置空环境变量可取消跳转。

## 本地桌面入口

运行 tools/install_desktop.ps1 后，桌面会出现“猫皇朝堂”和“猫皇朝堂设置”。前者双击检测 5060 Ti、加载本机 Ollama 后启动 API 并打开浏览器，后者切换自动、本地显卡或 Google AI 模式。

本地显卡模式无需 API Key。检测到 5060 Ti 后必须确认 Ollama 的 size_vram 大于零，才视为 GPU 就绪；未使用显存会报错，不会悄悄切换云端。显卡未连接时，只有已配置 Google 密钥才会改用云端。选填的配置保存在被 Git 忽略的 data/desktop-google.json。服务只监听 127.0.0.1，使用本机 data/ministers.db 保存历史，关闭网页后后台服务继续运行。桌面入口不依赖 Render；本地保存的密钥不会随源码发布。

官方依据：[Render 免费服务](https://render.com/docs/free)、[Gemini 定价](https://ai.google.dev/gemini-api/docs/pricing)、[兼容接口](https://ai.google.dev/gemini-api/docs/openai)。


## 2026-10-25 入口核查

已验证 https://the-ministers.onrender.com/api/health 返回 200 和 `{"ok":true}`，朝堂页面 `/front/The%20Court.dc.html` 返回 200。旧 Pages 页面未配置后端跳转，向 GitHub Pages 请求 `/api/health` 返回 404；其 “Court unavailable” 由此产生。personal-page 的入口已增加到上述 Render 朝堂页面的跳转，保留查询参数和锚点。此检查未使用访问口令，也未验证线上模型生成。

## 公开资料检索

`MINISTERS_WEB_RESEARCH=1`（默认）在开堂时按十二位大臣各自的情绪视角调用真实网络搜索。只把议题和情绪关键词发给搜索服务，不发送背景或用户文库。默认使用 Bing RSS；英文课题没有相关结果时用 Hacker News 的公开评论搜索作备用，并明确标注具体社区，不能代表全部公众；可选设置 `MINISTERS_SEARCH_API_KEY` 使用 Tavily Search，无需安装额外 SDK。搜索服务的额度以服务账号为准。

每位大臣最多两条摘要，保留原始链接，做课题词相关性过滤；查询、耗时、命中数及失败状态进入 retrieval 记录。摘要标为 `public_reaction`，不能冒充已核实事实、全文阅读或民意比例。检索失败或没有相关结果时，界面显示资料缺口。一次朝会只进行一批公开检索，后续发言复用资料；模型生成的台词不再写回事实文库。

开堂页新增 TXT、Markdown、JSON 上传和粘贴入口（200 KB），通过 `/api/library` 写入本机或当前服务的公共用户文库。用户文库仍受朝堂访问口令保护；共享口令的使用者共用文库。

讨论取消五轮上限，由用户点击“结束讨论 · 圣裁”停止。兼容字段 `rounds_left=null` 表示不限轮数，裁决后为 0。旧 SSE 接口每次请求最多生成一轮，防止取消上限后无人观看仍无限生成。前端使用按需生成，不依赖该流。

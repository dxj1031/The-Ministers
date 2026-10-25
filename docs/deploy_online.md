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

运行 tools/install_desktop.ps1 后，桌面会出现“猫皇朝堂”和“猫皇朝堂设置”。前者双击自动启动本地 API 并打开浏览器，后者重新填写 Google AI 密钥或模型名。

首次启动需填一次 Google API Key，保存在被 Git 忽略的 data/desktop-google.json。服务只监听 127.0.0.1，使用本机 data/ministers.db 保存历史，关闭网页后后台服务继续运行。桌面入口不依赖 Render；本地保存的密钥不会随源码发布。

官方依据：[Render 免费服务](https://render.com/docs/free)、[Gemini 定价](https://ai.google.dev/gemini-api/docs/pricing)、[兼容接口](https://ai.google.dev/gemini-api/docs/openai)。

# 校园客服 · 私有知识库智能客服

> 课程项目 · 团队：**沈凯杰、王瑞康**  
> 演示场景：虚构 **星云大学** 校园办事私有知识库  
> 演示门户：http://127.0.0.1:8787/

## 问题

企业内部客服文档问答最怕两件事：**大模型幻觉**，以及**答了却说不清依据**。  
在读证明、图书馆借阅、宿舍报修、校园网认证等口径必须可追溯到私有知识库；库外问题应明确拒答并转人工，而不是静默编造。

## 思路：多开源对照，取其精华，自研补短板

开题材料对照过 **Dify / RAGFlow / FastGPT / MaxKB**（及早期材料中的 LangChain·Rasa 思路）。  
我们**不堆叠安装全部引擎**，而是抽各自长处，用**一套可跑引擎 + 自研门户与约束层**落地 MVP：

| 开源项目 | 我们看中的长处 | 常见短板 / 不直接采用的原因 | 本项目如何吸收 |
|----------|----------------|-----------------------------|----------------|
| **Dify** | Workflow/Chatflow + RAG 编排快，自托管友好，适合客服知识库试跑 | 引用约束、空检索拒答仍易翻车，控制台不像「自研产品」 | **运行时主底座**：知识库检索、LLM 生成、Chatflow |
| **RAGFlow** | DeepDoc + 可溯源引用，复杂 PDF/版式理解强 | 客服编排、转人工、门户要另搭；本课样例是 Markdown FAQ | **理念借鉴**：回答必须可溯源；UI 强制展示引用卡片 |
| **FastGPT** | 知识库问答 + Flow/Agent 上手快 | 企业权限与失败约束仍需补；与 Dify 功能重叠 | **理念借鉴**：快捷 FAQ / 流程化问答体验 |
| **MaxKB** | Docker 易起，偏企业内网助手 | 引擎深度弱于 RAGFlow；授权需自查 | **理念借鉴**：内网私有部署、助手式客服形态 |
| LangChain 等 | 链路可控、组件可换 | 从零拼装成本高，本课周期不够 | **约束思路**：出口校验、空检索分支，而非换栈重写 |

一句话：**编排与检索复用成熟开源；「像自己的产品」的界面、引用门禁、空库拒答、转人工，我们自己做。**

## 本机启动（当前主线）

答辩和日常开发在你的 Windows 电脑上：Docker Desktop、Ollama（`bge-m3`）、Python 3.11+。线上 Render 先不动，`DEPLOY-RENDER.md` 只描述旧的轻量镜像。

```bash
cp .env.example .env          # 填入 DIFY_APP_API_KEY，不要把 .env 提交
# 知识库只导入 sample-kb/客服样例FAQ.md 这一个文件（144 条都在里面）
bash scripts/up-local.sh      # 有 Dify 目录就拉起 Dify，然后启动网关
# 或者不进容器，直接：
python3 server/proxy.py       # 默认 http://127.0.0.1:8080/
```

- 门户 `http://127.0.0.1:8080/`
- 坐席 `http://127.0.0.1:8080/agent`（演示账号 `agent1` / `agent123`）
- 后台 `http://127.0.0.1:8080/admin`（`admin` / `admin123`）
- 登录 `http://127.0.0.1:8080/login`
- Chatflow 草稿：`dify/campus-cs.chatflow.yml`（导入后绑定上面那一篇知识库，并换成你的 DeepSeek 模型）
- 评测：`python3 server/eval_runner.py --dataset tests/eval/test-set.json --group A`（B、C 需要本机 Dify，没跑就不要填数）

`LITE_MODE=1` 仍会走改造前的规则引擎，只给旧测试和旧 Render 镜像用。标签 `baseline-rules` 指在替换前的 `83463b9`。

## 架构（自研门户 + 开源引擎）

```
┌─────────────────────────────────────────────┐
│  校园客服门户 / 坐席 / 后台（自研）            │
│  http://127.0.0.1:8080/  /agent  /admin      │
└──────────────────┬──────────────────────────┘
                   │ POST /api/chat（无密钥）
                   ▼
┌─────────────────────────────────────────────┐
│  server/proxy.py + server/gateway.py        │
│  打码、空检索拦截、引用校验、按文档合并引用    │
│  工单、审计、自检、评测                        │
└──────────────────┬──────────────────────────┘
                   │ Bearer（仅服务端）
                   ▼
┌─────────────────────────────────────────────┐
│  Dify 1.19.0 Chatflow                        │
│  改写 → 检索 → 作答                           │
│  样例库：sample-kb/客服样例FAQ.md（一篇）      │
└─────────────────────────────────────────────┘
```

### 分工一览

| 能力 | 谁做 |
|------|------|
| 知识库分段 / 检索 / Chatflow 编排 / 模型调用 | **复用** Dify |
| 客服门户、坐席工作台、管理后台 | **自研** `web/` |
| 密钥不下发浏览器 | **自研** `server/proxy.py` |
| 引用校验、空检索拦截、按文档合并、打码 | **自研** `server/gateway.py` |
| 转人工队列、回写、坏例、审计、评测 | **自研** `server/agent_api.py`、`admin_api.py`、`eval_runner.py` |
| 查询改写、检索、生成 | **Dify Chatflow**（`dify/campus-cs.chatflow.yml`） |

引擎运维见：`/workspace/dify/RUNBOOK.md`（本仓库不提交密钥）。

## 演示 UI（已定稿 · E5）

生产门户视觉已确认落地为 **E5 贵宾席 · 苹果 R 角**（原 E 黑金 + 连续柔和圆角）：

- 演示地址：**http://127.0.0.1:8080/**（`LITE_MODE=1` 时仍是 8787，那是旧规则引擎）
- 设计说明：`docs/DESIGN.md`（confirmed）· 计划：`docs/PLAN.md` · 进度：`docs/STATUS.md`
- 截图证据：`docs/design/shots/prod-e5-1280.png` · UX：`docs/design/shots/ux-upgrade-1280.png` · Agent：`docs/design/shots/agent-upgrade-1280.png`
- 选款归档（静态原型仍可对照）：**http://127.0.0.1:8787/design/**
- UX（E5 交互升级，不做窄屏精修）：**SSE 流式 + 停止生成** · 空态主题 chips · 可展开出处卡 · `conversation_id` 多轮 / 本机会话历史 /「新对话」
- 门户在原有流式、停止、引用卡、本机会话之上，增加澄清选项、坐席回复和知识库维护提示。
- API：`POST /api/chat`（默认 SSE）· `POST /api/chat/stop` · `POST /api/ticket` · 坐席 `/api/agent/*` · 后台 `/api/admin/*`（后两者要登录）

## 目录

```
./
├── README.md
├── DEPLOY-RENDER.md      # Render Free（无卡 / LITE）说明
├── Dockerfile
├── render.yaml
├── requirements.txt
├── sample-kb/            # 校园办事 FAQ（Lite 自带）
├── docs/
│   ├── STATUS.md
│   ├── PRD.md
│   ├── DESIGN.md
│   ├── PLAN.md
│   └── design/           # 选款归档 + 截图
│       ├── index.html
│       ├── options/
│       └── shots/
├── web/                  # 生产客服门户（E5 已落地）
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── server/
│   ├── proxy.py          # HTTP 入口
│   ├── gateway.py        # 约束层
│   ├── agent_api.py
│   ├── admin_api.py
│   ├── auth.py
│   └── eval_runner.py
├── dify/
│   └── campus-cs.chatflow.yml
├── tests/eval/           # 测试集 / 开发集 / 冒烟题
└── scripts/
    ├── start-portal.sh   # 旧入口，仍可用
    └── up-local.sh       # Dify（若已放好）+ 网关
```

## 启动

日常用上面的「本机启动」。健康检查：

```bash
curl -s http://127.0.0.1:8080/api/health
```

旧的 Render Free 镜像仍然是 `Dockerfile` + `LITE_MODE=1`，说明在 `DEPLOY-RENDER.md`。那不是这次改造的运行方式。

```bash
LITE_MODE=1 PORTAL_PORT=8787 python3 server/proxy.py
```

## 演示话术

1. **有依据**：「在读证明如何办理？」→ 流式回答，右侧一张引用卡（同一篇文档的多段会折在一起）。  
2. **库外**：「怎么请病假？」→ 说明知识库里没有，不编规定，可以转人工。  
3. **含糊**：「证明怎么开？」→ 两三个选项，点一个再答。  
4. **转人工**：门户登记工单，坐席在 `/agent` 接入、回复；门户几秒内出现，并标「人工客服」。  
5. **安全**：浏览器里只有本站接口，看不到 Dify 或 DeepSeek 的密钥。手机号和证件号在出站前打码。

## 技术要点（答辩）

- 前端：纯 HTML/CSS/JS；**E5** 近黑+香槟金、苹果 R 角；Cormorant / Manrope + 中文系统字体。  
- 代理：Python 3 `http.server`；blocking 转发；去掉模型 thinking 标签。  
- 样例库：`sample-kb/客服样例FAQ.md` 一个文件、144 条。Dify 里导入这一篇。  
- 硬约束：库外不瞎答、回答可展示来源、密钥仅服务端。

## 声明

校园办事 FAQ 为课程虚构样例，不代表任何真实高校政策。对用户显示的名称是「校园客服 / 校园助手」；「星云大学」只是虚构校园。仓库名、Render 服务名仍是 nebula-cs。非办事请求会说明服务范围，不再走算式、翻译或开放闲聊。没有配上 Dify 时，办事问题进入「知识库维护中」并登记人工，而不是改回规则引擎作答。

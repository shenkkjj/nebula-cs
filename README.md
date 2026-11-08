# 星云客服 · 私有知识库智能客服

> 课程项目 · 团队：**沈凯杰、王瑞康**  
> 演示产品：虚构智能水杯 **CloudCup Pro**  
> 演示门户：http://127.0.0.1:8787/

## 问题

企业内部客服文档问答最怕两件事：**大模型幻觉**，以及**答了却说不清依据**。  
保修、清洗、退换货等政策必须可追溯到私有知识库；库外问题应明确拒答并转人工，而不是静默编造。

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

## 架构（自研门户 + 开源引擎）

```
┌─────────────────────────────────────────────┐
│  星云客服门户（自研）  http://127.0.0.1:8787 │
│  · 中文客服 UI / FAQ 快捷提问 / 引用侧栏     │
│  · 拒答提示 / 转人工 / 助手 framing           │
└──────────────────┬──────────────────────────┘
                   │ POST /api/chat（无密钥）
                   ▼
┌─────────────────────────────────────────────┐
│  本地代理 server/proxy.py（自研）             │
│  · 托管静态页 · 注入引擎 Key · 清洗 thinking  │
│  · 查询改写 / 转人工意图 / 订单存根            │
│  · 整形 {answer, citations, refuse, …}       │
└──────────────────┬──────────────────────────┘
                   │ Bearer（仅服务端）
                   ▼
┌─────────────────────────────────────────────┐
│  开源引擎：Dify Chatflow（本机 Docker）      │
│  知识库检索 → LLM → Answer（引用 / 空检索拒答）│
│  样例 FAQ：CloudCup Pro 48 条                │
└─────────────────────────────────────────────┘
```

### 分工一览

| 能力 | 谁做 |
|------|------|
| 知识库分段 / 检索 / Chatflow 编排 / 模型调用 | **复用** Dify |
| 客服门户视觉与交互（非控制台皮肤） | **自研** `web/` |
| API Key 不下发浏览器的本地代理 | **自研** `server/proxy.py` |
| 引用卡片展示（文档名 / 相关度 / 片段） | **自研**（消费引擎 `retriever_resources`） |
| 空检索 / 无依据 → 拒答文案与 UI 标记 | **自研门禁** + 引擎侧空分支配置 |
| 转人工演示工单 | **自研**本地存根（意图识别 + `POST /api/ticket`） |
| 多轮查询改写 / 订单存根 | **自研** proxy Agent 层 |

引擎运维见：`/workspace/dify/RUNBOOK.md`（本仓库不提交密钥）。

## 演示 UI（已定稿 · E5）

生产门户视觉已确认落地为 **E5 贵宾席 · 苹果 R 角**（原 E 黑金 + 连续柔和圆角）：

- 演示地址：**http://127.0.0.1:8787/**
- 设计说明：`docs/DESIGN.md`（confirmed）· 计划：`docs/PLAN.md` · 进度：`docs/STATUS.md`
- 截图证据：`docs/design/shots/prod-e5-1280.png` · UX：`docs/design/shots/ux-upgrade-1280.png` · Agent：`docs/design/shots/agent-upgrade-1280.png`
- 选款归档（静态原型仍可对照）：**http://127.0.0.1:8787/design/**
- UX（E5 交互升级，不做窄屏精修）：**SSE 流式 + 停止生成** · 空态主题 chips · 可展开出处卡 · `conversation_id` 多轮 / 本机会话历史 /「新对话」
- Agent 最小升级：**查询改写**（短指代追问）· **转人工**意图与演示工单 · 文案「智能客服助手」· **订单存根**（`ORD*`）
- API：`POST /api/chat`（可带 `history`；默认 SSE；`stream:false` 阻塞 JSON）· `POST /api/chat/stop` · `POST /api/ticket`

## 目录

```
./
├── README.md
├── DEPLOY-RENDER.md      # Render Free（无卡 / LITE）说明
├── Dockerfile
├── render.yaml
├── requirements.txt
├── sample-kb/            # CloudCup FAQ（Lite 自带）
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
│   └── proxy.py          # 静态托管 + /design/ + API 代理
└── scripts/
    └── start-portal.sh
```

## 启动

### Render Free / 无卡轻量模式（LITE）

完整 Dify Docker **塞不进** Render Free（~512MB）。无卡部署请用本地 FAQ 轻量引擎，见 **`DEPLOY-RENDER.md`**：

```bash
LITE_MODE=1 PORTAL_PORT=8787 python3 server/proxy.py
# 可选：export DEEPSEEK_API_KEY=...  （无 Key 时用 FAQ 模板作答，演示仍可用）
```

Blueprint：`render.yaml` · 镜像：`Dockerfile`


**前置**：Dify 已启动（`/workspace/dify/start.sh`），应用 API Key 在本机文件（勿入库）。

```bash
bash scripts/start-portal.sh
```

打开：**http://127.0.0.1:8787/**

可选环境变量：`PORTAL_PORT`、`DIFY_APP_API_KEY` / `DIFY_APP_API_KEY_FILE`、`DIFY_CHAT_URL`。

```bash
curl -s http://127.0.0.1:8787/api/health
```

## 演示话术

1. **有依据**：「保修政策是怎样的？」→ 整机 **12 个月**、电池/密封圈 **6 个月**；右侧引用 `客服样例FAQ.md`。  
2. **快捷 FAQ**：顶栏芯片点选清洗 / 指示灯 / 退换货等。  
3. **拒答**：「帮我把订单改寄到火星并开发票」→ 未找到依据 / 建议转人工。  
4. **转人工**：右上角或拒答气泡 → 提交演示工单（本地回执号）。  
5. **安全**：DevTools 里只见 `/api/chat`，看不到引擎 API Key。

## 技术要点（答辩）

- 前端：纯 HTML/CSS/JS；**E5** 近黑+香槟金、苹果 R 角；Cormorant / Manrope + 中文系统字体。  
- 代理：Python 3 `http.server`；blocking 转发；去掉模型 thinking 标签。  
- 样例库：`sample-kb/客服样例FAQ.md`（Lite / Render）。完整 Dify 演示仍可读课程机 `/workspace/dify/sample-kb/客服样例FAQ.md`。  
- 硬约束：库外不瞎答、回答可展示来源、密钥仅服务端。

## 声明

CloudCup Pro 与 FAQ 为课程虚构样例。品牌名使用「星云客服 / CloudCup 智能客服」。

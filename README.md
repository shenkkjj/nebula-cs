# 校园客服 · 私有知识库智能客服

> 课程项目 · 团队：**沈凯杰、王瑞康**  
> 演示场景：虚构 **星云大学** 校园办事私有知识库  
> 演示门户：http://127.0.0.1:8080/（默认是自建知识库。`LITE_MODE=1` 的旧规则入口仍是 8787）

## 问题

企业内部客服文档问答最怕两件事：**大模型幻觉**，以及**答了却说不清依据**。  
在读证明、图书馆借阅、宿舍报修、校园网认证等口径必须可追溯到私有知识库；库外问题应明确拒答并转人工，而不是静默编造。

## 思路

开题材料对照过 Dify、RAGFlow、FastGPT、MaxKB，向量库从 Chroma 起步、以后可以迁到 Milvus。正式产品**不安装那些重平台**，这次也不迁 Milvus，也不把 LangChain 当成应用框架。检索、知识库和门户都在这一个 Python 进程里：标准库 SQLite 存文档和分段，自写的中文 FAQ 词法索引（BM25）始终负责检索。配了 `EMBEDDING_API_KEY` 和 `EMBEDDING_BASE_URL` 之后，分段向量写进**嵌入式 Chroma**（`chromadb` 的 `PersistentClient`，数据在 `DATA_DIR/chroma`），和词法结果一起排序。不配密钥、或者 Chroma 加载失败，仍然只用词法回答。对话模型是 DeepSeek 的 HTTP 接口，密钥只在服务端。

Chroma 只做向量近邻。没有把 BM25 换成 Chroma 自带的全文索引，也没有换成 SQLite FTS5：现有词表会挡住「办理 / 申请」这类空词把不相干的条目拖进来，FTS5 的默认分词对中文会拆成单字。流水线是「改写 → 词法检索，必要时再查 Chroma → 混合排序 → 只根据命中的分段作答并附出处」。这是开题里说的 LangChain 式 RAG 形状，代码里没有 LangChain。

没有当作运行时底座的重平台：

| 平台 | 不作为运行时的原因 |
|------|-------------------|
| Dify | 要 Docker、Postgres、向量服务和工作流 Worker，2 GiB 机器放不下整套 |
| RAGFlow / FastGPT / MaxKB | 同样是带数据库和模型服务的一体化平台 |
| Ollama / 本地嵌入模型 | 不安装，默认也不启用。Chroma 自带的 ONNX MiniLM 没有接上，2 GiB 机器不要打开它 |
| LangChain | 不作为应用框架。路由、检索和约束是普通 Python 函数 |
| Milvus | 开题里的后续向量库，这次不迁 |

`ENGINE=dify` 仍可把旧的 Dify 网关拉起来，只供对照，不是默认。

## 本机启动（默认）

需要 Python 3.11+。不需要 Docker、Ollama 或 Dify。浏览器窗口宽至少 1280px。

```bash
cp .env.example .env          # 可先不填密钥。不要提交 .env
# 只有要用远程向量时才装 Chroma。不装也能答。
# pip install -r requirements-campus.txt
bash scripts/up-campus.sh     # http://127.0.0.1:8080/
# 等价于：
# ENGINE=campus python3 server/proxy.py
```

- 门户 `http://127.0.0.1:8080/`
- 坐席 `http://127.0.0.1:8080/agent`（`agent1` / `agent123`）
- 后台 `http://127.0.0.1:8080/admin`（`admin` / `admin123`）
- 登录 `http://127.0.0.1:8080/login`
- 样例库在第一次启动时从 `sample-kb/客服样例FAQ.md` 导入（一个文件、144 条）
- 测试：`python3 -m unittest discover -s tests`

没有 `DEEPSEEK_API_KEY` 时，办事问答用知识库原文（先一句，再细节和出处）。闲聊和写作会说明需要配置模型。配上密钥后，办事回答仍必须能对上检索片段，对不上的数字会退回原文。

旧入口仍在，但不是这套正式产品：

```bash
LITE_MODE=1 PORTAL_PORT=8787 python3 server/proxy.py   # 旧规则引擎
ENGINE=dify python3 server/proxy.py                    # 旧 Dify 网关，需自备 Dify
bash scripts/up-local.sh                               # 可选：本机已有 Dify 时的旧脚本
```

`render.yaml` 和 `Dockerfile` 仍是 `LITE_MODE=1` 的旧镜像，这次不改线上部署。

## 架构（默认：自建知识库）

```
门户 / 坐席 / 后台（web/）
        │  POST /api/chat（浏览器不持有密钥）
        ▼
server/proxy.py
        │  ENGINE=campus（默认）
        ▼
意图 → 追问改写 → 词法检索（可选：嵌入式 Chroma）
        │
        ├─ 办事：只根据命中的分段作答，附出处；没有条目就说明原因并可转人工
        ├─ 含糊：只问一个澄清问题
        └─ 闲聊 / 写作：DeepSeek（可选），不得把校规说成知识库里有
        │
        ▼
SQLite（DATA_DIR/nebula.sqlite）
  文档、分段、工单、审计、判定
Chroma（DATA_DIR/chroma，仅在配置了远程嵌入且加载成功时）
  分段向量。进程内库，没有单独的数据库服务
```

| 能力 | 位置 |
|------|------|
| 文档与分段的增删改 | `server/kb_store.py`，后台「知识库文档 / 分段」 |
| 词法检索；配了远程嵌入时用 Chroma 做混合排序 | `server/kb_retrieve.py`、`server/chroma_store.py` |
| 意图、改写、拒答、流式 | `server/campus_engine.py` |
| 转人工队列、回写进知识库 | `server/agent_api.py`，坐席「回写知识库」 |
| 会话与工单回看 | 后台「会话与转人工」 |
| 旧 Dify 约束层 | `ENGINE=dify` 时仍走 `server/gateway.py` |
| 旧规则引擎 | `LITE_MODE=1` 时仍走 `server/lite_engine.py` |

### 环境变量

| 变量 | 作用 |
|------|------|
| `ENGINE` | `campus`（默认）、`dify`、`lite`。显式值优先于 `LITE_MODE` |
| `DEEPSEEK_API_KEY` | 可选。不填则办事用原文，闲聊会说明缺模型 |
| `DEEPSEEK_MODEL` | 默认 `deepseek-chat` |
| `DEEPSEEK_API_URL` | 默认 `https://api.deepseek.com/chat/completions` |
| `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | 可选。OpenAI 兼容的 `/embeddings`。不填则只用词法。填了则向量写入嵌入式 Chroma |
| `DATA_DIR` | SQLite 与 Chroma 目录，默认 `./data`，不进仓库。Chroma 文件在 `DATA_DIR/chroma` |
| `DIFY_*` | 只在 `ENGINE=dify` 时使用 |

后台「生成向量」会调用远程嵌入接口，把结果写入 Chroma。Chroma 没装上、没加载成功，或嵌入接口失败，都不影响词法检索。日志里会有 `lexical-only`。

### 2 GiB 内存（实测的是进程，不是整机）

`python3 scripts/measure_rss.py` 在这台开发机上导入 144 条并回答 8 个问题。嵌入密钥是空的，进程没有 import `chromadb`。

| 读数 | 值 |
|------|----|
| 分段 | 144 |
| SQLite 文件 | 168 KiB（172032 字节） |
| 词法路径峰值 RSS（`ru_maxrss`） | **26.6 MiB** |
| 当时 `VmRSS` / `VmHWM` | **26.7 MiB** |
| 同一进程再打开嵌入式 Chroma（空集合，不加载 ONNX 嵌入模型）之后的峰值 | **96.6 MiB**（`VmRSS` 96.8 MiB） |
| 单独一个只打开 Chroma 客户端的进程 | 峰值 **96.9 MiB** |

据此做的预算，不是在华为 Flexus 上的整机实测：

| 部分 | 量级 |
|------|------|
| 默认进程（解释器 + 144 段词法索引，不加载 Chroma） | 约 27–80 MiB |
| 打开嵌入式 Chroma、但不加载它自带的 ONNX MiniLM | 这次测到约 100 MiB。分段向量本身很小：144 段 × 1536 维 × 4 字节约 1 MiB |
| 一次 DeepSeek 或远程嵌入调用 | 只保留请求和回答文本，不在本机加载权重 |
| 操作系统和其他进程 | 2 GiB 机器上通常要占数百 MiB，这一项没有在 Flexus 上量过 |

应用进程即使把 Chroma 客户端算进去，仍然远小于 2 GiB。整机是否从容，取决于系统和其他服务，不能只凭这 27 MiB 或 97 MiB 宣称「已经在 Flexus 上稳跑」。没有把 Dify、FastGPT、RAGFlow、MaxKB、Postgres、Milvus 或 Ollama 算进去；那些才是会把 2 GiB 吃满的部分。Chroma 自带的本地嵌入模型没有接上，不要在这台机器上打开。

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
├── requirements.txt      # Render / LITE 镜像：不安装 Chroma
├── requirements-campus.txt  # 可选：pip install 后才有嵌入式 Chroma
├── sample-kb/            # 启动时导入的 144 条 FAQ
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
│   ├── campus_engine.py  # 默认：意图、改写、作答
│   ├── kb_store.py       # SQLite 文档与分段
│   ├── kb_retrieve.py    # 词法检索；有向量时和 Chroma 混合排序
│   ├── chroma_store.py   # 嵌入式 Chroma，加载失败则退回词法
│   ├── chroma_runtime.py # 用到向量时才加载 chromadb，不启用自带 ONNX 嵌入
│   ├── gateway.py        # 仅 ENGINE=dify
│   ├── agent_api.py
│   ├── admin_api.py
│   └── eval_runner.py
├── dify/
│   └── campus-cs.chatflow.yml
├── tests/eval/           # 测试集 / 开发集 / 冒烟题
└── scripts/
    ├── up-campus.sh      # 默认启动
    ├── up-local.sh       # 可选：本机已有 Dify 时
    └── measure_rss.py    # 进程内存
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
5. **闲聊**：「帮我写一首短诗」→ 不附校规出处。没有模型密钥时会说明。  
6. **安全**：浏览器里只有本站接口，看不到 DeepSeek 密钥。手机号和证件号在出站前打码。

## 技术要点（答辩）

- 前端：纯 HTML/CSS/JS；**E5** 近黑+香槟金、苹果 R 角；Cormorant / Manrope + 中文系统字体。  
- 代理：Python 3 `http.server`；默认 SSE；去掉模型 thinking 标签。  
- 样例库：`sample-kb/客服样例FAQ.md` 一个文件、144 条，第一次启动写入 SQLite。  
- 检索：BM25 一直可用；远程嵌入写进嵌入式 Chroma，和词法一起排序。加载失败就只用词法。
- 硬约束：办事口径不编造、回答可展示来源、密钥仅服务端。

## 声明

校园办事 FAQ 为课程虚构样例，不代表任何真实高校政策。对用户显示的名称是「校园客服 / 校园助手」；「星云大学」只是虚构校园。仓库名、Render 服务名仍是 nebula-cs。办事规定只按知识库回答；库里没有的会说明原因，并可以转人工。日常闲聊和写作可以使用，但不得把校规编造成知识库内容。

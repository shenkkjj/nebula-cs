# 校园客服 · 开发计划

- **版本 / 日期**：v1.0 | 2026-11-14
- **依据基准**：PRD v1.0（2026-11-14 已确认）｜DESIGN v1.0（2026-11-14 已确认）｜推进节奏 standard
- **整体交付入口与承诺宿主**：H1 用户访问 `http://localhost:8080/`，坐席访问 `/agent`，管理员访问 `/admin`，登录访问 `/login`；H2 生产部署通过 Docker Compose 启动 Dify + 本地代理

## 1. 用户确认记录

- **状态**：待确认
- **确认方式**：整版确认
- **用户原话 / 来源与日期**：待确认

## 2. 技术基础决策

| 维度 | 本项目确定选择、路径或真实命令 |
|---|---|
| 平台与目录树 | Windows 本地开发，生产 Docker Compose；根目录 `nebula-cs/`，前端 `web/`，后端 `server/`，设计原型 `docs/design/`，测试集 `tests/eval/` |
| 语言与运行时 | Python 3.11+（后端代理、评测脚本）；原生 HTML/CSS/JS（前端，无构建） |
| Dify 引擎 | Dify 1.19.0 docker-compose 本地部署（需 Docker Desktop），课程机 `/workspace/dify` 或本地新建 |
| 模型与嵌入 | DeepSeek Chat（已有 key）；Ollama bge-m3（本地嵌入，`ollama pull bge-m3`） |
| 依赖安装 | `pip install -r requirements.txt`（Flask, httpx, python-dotenv）；前端无依赖 |
| 环境变量与密钥 | `DIFY_APP_API_KEY`（从 Dify 应用获取）、`DEEPSEEK_API_KEY`（评测用）、`DIFY_CHAT_URL`（默认 `http://127.0.0.1/v1/chat-messages`） |
| 启动命令 | 开发：`python server/proxy.py`（默认 8080 端口）；生产：`docker-compose up -d` |
| 测试与验证 | 评测：`python server/eval_runner.py --dataset tests/eval/test-set.json`；操作验证见各阶段 |
| 复核工具 | Playwright（交互自动化）、Edge/Chrome 手动验收 |

## 3. 需求与设计覆盖检查

| R-ID | 对应页面/模块 + 设计检查 ID | 待验证前提 | 状态 | 验证方法 |
|---|---|---|---|---|
| R-101 | 门户 `web/index.html` + D1 引用卡合并 | Dify Chatflow 返回 retriever_resources | todo | 浏览器操作 + 检查引用卡数量 |
| R-102 | 门户 + D1 | 同上 | todo | 同上 |
| R-103 | 门户 + D2 澄清 chip | Dify Chatflow 返回 `clarify: [...]` | todo | 点 chip 后检查问题替换 |
| R-104 | 门户 + D4 维护通知 | 网关 `/v1/probe` 返回失败 | todo | 模拟探针失败，检查顶栏和通知条 |
| R-105 | 门户 + 网关非办事判定 | 网关识别问候/非办事 | todo | 输入「你好」「帮我写诗」检查回应 |
| R-106 | 门户 + D3 坐席回复 + 坐席工作台 | 网关 `/v1/ticket` 创建工单，坐席回复写入数据库 | todo | 转人工 → 坐席回复 → 门户显示 |
| R-107 | 门户（已有） | 无 | done | 回归测试 |
| R-201 | 网关约束层 | Dify 返回 retriever_resources | todo | 检查引用校验逻辑 |
| R-202 | 网关约束层 | Dify 返回空 retriever_resources | todo | 空检索拦截测试 |
| R-203 | 网关约束层 + D1 | Dify 返回多段同文档 | todo | 检查按文档合并 |
| R-204 | 后台自检 + 探针 + D4 | Dify 应用绑定知识库 | todo | 运行探针，检查红绿灯 |
| R-205 | 网关打码 | 无 | todo | 输入手机号/证件号检查打码 |
| R-301 | 坐席工作台 `web/agent.html` + D5 | 工单数据库（SQLite） | todo | 浏览器操作队列、对话 |
| R-302 | 坐席工作台 + D6 判定详情 | 网关记录每轮判定 | todo | 右侧面板显示追溯步骤 |
| R-303 | 坐席工作台 + D7 回复与结束 | 工单状态流转 | todo | 回复发送、结束工单验证 |
| R-304 | 坐席工作台 + D8 回写知识库 | Dify 知识库 API（上传文档） | todo | 提交回写 → 检查索引状态 |
| R-305 | 坐席工作台 + D9 标记坏例 | 评测集文件 `tests/eval/bad-cases.json` | todo | 提交坏例 → 文件追加记录 |
| R-401 | 后台 `web/admin.html` 知识库文档 | Dify 知识库 API | todo | 列表、删除操作 |
| R-402 | 后台自检 | 探针逻辑 | todo | 手动触发自检 |
| R-403 | 后台审计日志 + D10 | 审计数据库表 | todo | 浏览器查看、展开行 |
| R-404 | 后台约束参数 | 参数配置文件 `server/config.json` | todo | 修改阈值、重启生效 |
| R-501 | 后台评测 | 测试集 `tests/eval/test-set.json` | todo | 浏览器选择数据集 |
| R-502 | 后台评测 + D11 | `server/eval_runner.py` | todo | 运行评测、导出 MD/CSV |
| R-503 | 后台评测 + D11 | A 组标签 `git tag baseline-rules`，B/C 组代码分支 | todo | 三组对照表格 |
| R-504 | 评测校准 | 人工标注 30 题 | todo | 计算一致率 |
| SEC-002 | 登录页 `web/login.html` | 用户表（SQLite），密码哈希 | todo | 登录成功跳转 |

## 4. 阶段卡

### T1 — 网关与约束层核心

- **范围与不做**：实现 `server/gateway.py`（接收门户请求 → 调 Dify → 约束层判定 → 返回）；约束层包括 R-201 引用校验、R-202 空检索拦截、R-203 按文档合并、R-205 打码。**不做**：坐席工单、后台、评测。
- **运行入口与数据前提**：
  - Dify 本地运行（`docker-compose up -d`），已创建 Chatflow 应用并绑定知识库，环境变量 `DIFY_APP_API_KEY` 已设置
  - `python server/proxy.py`，浏览器访问 `http://localhost:8080/`
  - 测试输入：「在读证明如何办理？」（应返回引用）、「怎么请病假？」（空检索，应拦截）
- **验收动作 / 预期 / 失败信号**：
  - 输入范围内问题 → 流式回答 + 引用卡显示来源文档；失败信号：无引用或引用重复（R-101, R-102, D1）
  - 输入缺失条目问题 → 「知识库里没有…」拒答模板 + 转人工按钮；失败信号：模型自由发挥（R-102, R-202）
  - 输入手机号/证件号 → 日志显示打码，前端不回显原文；失败信号：明文泄漏（R-205）
  - 同一文档多段 → 引用卡只显示一张；失败信号：重复卡片（R-203, D1）
- **自检与独立复核范围**：
  - 单元测试 `tests/test_gateway.py`（pytest）：测试打码、合并、拦截逻辑
  - 集成测试：5 个样例问题（范围内、空检索、非办事、打码、澄清），检查返回结构
  - 截图证据存 `docs/evidence/T1-gateway-constraints.png`（引用卡、拒答、打码后日志）
- **执行记录**：候选提交 `<hash>`｜自检证据 `<路径>`｜审查报告 `<路径>`

### T2 — 门户新增状态

- **范围与不做**：在 `web/index.html` 和 `web/app.js` 中新增 R-103 澄清选项、R-104 知识库维护通知、R-106 坐席回复显示。**不做**：坐席端实现（T3 做）。
- **运行入口与数据前提**：
  - T1 已完成，网关运行
  - 测试澄清：网关返回 `{"clarify": ["在读证明", "成绩证明"]}`（需 Chatflow 支持或网关模拟）
  - 测试维护：手动停止 Dify 或修改探针返回，触发 R-204 失败
  - 测试坐席回复：工单表插入一条模拟回复记录
- **验收动作 / 预期 / 失败信号**：
  - 输入「证明怎么开？」→ 机器人显示 2-3 个 chip；点击 chip → 按选中问题回答；失败信号：chip 无响应（R-103, D2）
  - 探针失败 → 顶栏黄色「知识库维护中」+ 页面顶部通知条 + 新问题自动建工单；失败信号：仍显示「助手在线」（R-104, D4）
  - 坐席回复后 → 5 秒内门户显示消息，标「人工客服」，底栏显示工单号；失败信号：不显示或标记错误（R-106, D3）
- **自检与独立复核范围**：
  - Playwright 自动化：模拟澄清、维护、坐席回复三种场景，截图验证
  - 手动验收：刷新浏览器后仍能看到坐席回复（localStorage 或 sessionStorage）
  - 截图证据 `docs/evidence/T2-portal-states/`（三种状态各一张）
- **执行记录**：候选提交 `<hash>`｜自检证据 `<路径>`｜审查报告 `<路径>`

### T3 — 坐席工作台

- **范围与不做**：实现 `web/agent.html` 和 `server/agent_api.py`（工单 CRUD、队列、回复、结束工单、回写知识库、标记坏例）。**不做**：后台管理（T4 做）、评测（T5 做）。
- **运行入口与数据前提**：
  - T1、T2 已完成
  - 数据库表：`tickets`（工单）、`messages`（对话）、`judgments`（判定记录）
  - 浏览器访问 `http://localhost:8080/agent`（暂时跳过登录，T6 补）
  - 测试数据：工单表插入 2 条「待接入」、1 条「处理中」
- **验收动作 / 预期 / 失败信号**：
  - 队列切换（待接入/处理中/已结束）→ 卡片列表更新；点卡片 → 中间显示对话，右侧显示判定详情；失败信号：卡片不响应（R-301, D5）
  - 判定详情 tab → 显示改写、检索、约束、输出四步，带时间和结果；失败信号：步骤缺失（R-302, D6）
  - 回复框输入 + Enter → 消息追加到对话，发送给用户（经 WebSocket 或轮询）；结束工单弹层空说明提交 → 被拒；填写说明 → 工单状态变「已结束」；失败信号：空说明通过（R-303, D7）
  - 回写知识库 tab：填问题和答法 → 提交 → 状态显示「索引中」→ 1-2 秒后变「索引完成」；失败信号：状态不切换（R-304, D8）
  - 标记坏例 tab：未选类型提交 → 被拒；选类型 + 填期望 → 提交 → `tests/eval/bad-cases.json` 追加一条；失败信号：未选类型通过（R-305, D9）
- **自检与独立复核范围**：
  - 单元测试 `tests/test_agent_api.py`：工单 CRUD、状态流转
  - Playwright 自动化：队列切换、回复发送、回写提交、坏例标记
  - 双窗口验收（H1）：门户窗口 + 坐席窗口，门户转人工 → 坐席接入 → 回复 → 门户显示
  - 截图证据 `docs/evidence/T3-agent/`（队列、对话、判定、回写、坏例各一张）
- **执行记录**：候选提交 `<hash>`｜自检证据 `<路径>`｜审查报告 `<路径>`

### T4 — 管理后台

- **范围与不做**：实现 `web/admin.html` 和 `server/admin_api.py`（知识库文档列表/删除、绑定自检、审计日志、约束参数配置）。**不做**：评测（T5 做）、登录（T6 做）。
- **运行入口与数据前提**：
  - T1-T3 已完成
  - 浏览器访问 `http://localhost:8080/admin`
  - 审计表有若干条记录（从 T1-T3 自动积累）
- **验收动作 / 预期 / 失败信号**：
  - 知识库文档页 → 列出文档（调 Dify API），点删除 → 文档移除；失败信号：删除后仍显示（R-401）
  - 绑定自检页 → 显示红绿灯、三项检查结果、上次自检时间；点「立即自检」→ 运行探针，更新状态；失败信号：探针失败时仍显示绿灯（R-402, R-204, D4）
  - 审计日志页 → 表格显示时间、会话、问题、判定、来源、时延；点展开按钮 → detail-row 显示该轮追溯（改写、检索、约束、输出）；失败信号：展开无内容（R-403, D10）
  - 约束参数页 → 显示当前阈值（检索 top-k、相关度阈值）；修改后保存 → 写入 `server/config.json`；重启代理 → 新参数生效；失败信号：修改不生效（R-404）
- **自检与独立复核范围**：
  - 单元测试 `tests/test_admin_api.py`：知识库 API、探针逻辑、审计查询
  - Playwright 自动化：文档删除、自检触发、审计展开、参数修改
  - 截图证据 `docs/evidence/T4-admin/`（知识库、自检、审计、参数各一张）
- **执行记录**：候选提交 `<hash>`｜自检证据 `<路径>`｜审查报告 `<路径>`

### T5 — 评测与指标

- **范围与不做**：实现 `server/eval_runner.py`（运行评测、计算指标、导出 MD/CSV）和后台评测页（`web/admin.html#eval`）。**不做**：其他功能。
- **运行入口与数据前提**：
  - T1-T4 已完成
  - 测试集 `tests/eval/test-set.json`（107 题，已准备）、开发集 `tests/eval/dev-set.json`、坏例集 `tests/eval/bad-cases.json`（从 T3 积累）
  - 环境变量 `DEEPSEEK_API_KEY` 已设置（评测用）
  - A 组基线：`git tag baseline-rules` 标记旧版规则引擎代码
  - B 组：Dify Chatflow 直出（绕过网关约束层）
  - C 组：当前系统（网关 + 约束层）
- **验收动作 / 预期 / 失败信号**：
  - 命令行运行 `python server/eval_runner.py --dataset tests/eval/test-set.json --group C` → 输出指标（范围内正确率、Hit@3、库外拒答率、误拒率、重复引用、时延），生成 `results/eval-C-test.json`；失败信号：脚本报错（R-501, R-502）
  - 后台评测页：选数据集（测试/开发/坏例）+ 对照组（A/B/C）→ 点运行 → 显示进度 → 结果表格显示三组指标，达标项标绿色 badge；点导出 Markdown → 下载 `.md` 文件；点导出 CSV → 下载逐题明细；失败信号：导出内容缺失（R-502, D11）
  - 三组对照表格并排显示，指标行有目标值和实际值；失败信号：缺 A 或 B 组（R-503, D11）
  - 随机抽 30 题人工判分，计算自动判分一致率，写入 `docs/evidence/T5-eval-calibration.md`；失败信号：一致率 < 80%（R-504）
- **自检与独立复核范围**：
  - 单元测试 `tests/test_eval_runner.py`：判分逻辑、指标计算
  - 集成测试：运行小样本（10 题）评测，检查输出格式
  - 实测：测试集 107 题 × 3 组，记录耗时和费用
  - 截图证据 `docs/evidence/T5-eval/`（后台评测页、三组对照表格、导出 MD 示例）
- **执行记录**：候选提交 `<hash>`｜自检证据 `<路径>`｜审查报告 `<路径>`

### T6 — 登录与部署

- **范围与不做**：实现 `web/login.html` 和 `server/auth.py`（用户认证、会话管理）；补全 Docker Compose 配置（Dify + 本地代理 + 数据库持久化）。**不做**：新功能。
- **运行入口与数据前提**：
  - T1-T5 已完成
  - 用户表：`users`（username, password_hash, role: agent/admin）
  - 初始用户：`admin/admin123`（管理员）、`agent1/agent123`（坐席）
- **验收动作 / 预期 / 失败信号**：
  - 访问 `/agent` 或 `/admin` 未登录 → 302 跳转到 `/login`；登录成功 → 302 跳转回原页面；失败信号：未登录可访问（SEC-002）
  - `docker-compose up -d` → Dify + 代理 + 数据库全部启动；访问 `http://localhost:8080/` → 门户正常；失败信号：容器启动失败（H2）
- **自检与独立复核范围**：
  - 单元测试 `tests/test_auth.py`：登录逻辑、会话验证
  - Docker 验收：全新环境 `docker-compose up`，检查所有功能
  - 截图证据 `docs/evidence/T6-login-deploy.png`（登录页 + 成功跳转）
- **执行记录**：候选提交 `<hash>`｜自检证据 `<路径>`｜审查报告 `<路径>`

### T7 — 最终验收与证据

- **范围与不做**：回归测试所有 R-ID 和 D-ID，补全缺失证据，生成最终报告附件。**不做**：新开发。
- **运行入口与数据前提**：T1-T6 全部完成，Docker Compose 环境干净启动
- **验收动作 / 预期 / 失败信号**：
  - 遍历 DESIGN.md 表 4 所有检查 ID（D1-D13），逐项操作并截图；失败信号：任一项不符合设计约定
  - 遍历 PRD.md 表 3.1-3.5 所有 R-ID，逐项验证并记录；失败信号：任一必过项未实现
  - 指标实测（§3.6）：测试集 107 题，C 组达到目标值；失败信号：正确率 < 85%
  - 生成 `docs/evidence/final-acceptance.md`（汇总所有证据路径 + 指标结果）
- **自检与独立复核范围**：
  - 独立审查员读取 PRD、DESIGN、PLAN、所有证据，确认覆盖完整
  - 最终截图集 `docs/evidence/final-screenshots/`（门户、坐席、后台、评测各主要页面）
- **执行记录**：候选提交 `<hash>`｜自检证据 `<路径>`｜审查报告 `<路径>`

## 5. 用户需要做的事（门槛与验证）

| 事项 | 时机 | 具体动作 | 验证通过条件 |
|---|---|---|---|
| 安装 Docker Desktop | T1 前 | 下载安装并启动 Docker Desktop | `docker --version` 和 `docker-compose --version` 有输出 |
| 部署 Dify 本地实例 | T1 前 | 课程机 `/workspace/dify` 或本地 `git clone` Dify 仓库，`docker-compose up -d` | 访问 `http://127.0.0.1` 打开 Dify 控制台 |
| 创建 Chatflow 应用 | T1 前 | Dify 控制台创建应用，类型 Chatflow，绑定知识库，添加 Knowledge Retrieval 节点，获取 API key | API key 形如 `app-xxx...`，长度 > 20 |
| 上传知识库文档 | T1 前 | Dify 控制台创建知识库「星云大学办事」，上传 `sample-kb/*.md` 144 个文件 | 知识库显示 144 篇文档，索引完成 |
| 安装 Ollama 并拉取 bge-m3 | T1 前 | `ollama pull bge-m3` | `ollama list` 显示 bge-m3 |
| 配置环境变量 | T1 前 | 新建 `.env` 文件：`DIFY_APP_API_KEY=app-xxx`、`DEEPSEEK_API_KEY=sk-xxx`、`DIFY_CHAT_URL=http://127.0.0.1/v1/chat-messages` | `python server/proxy.py` 启动无报错 |
| 准备测试集 | T5 前 | 确认 `tests/eval/test-set.json` 和 `tests/eval/dev-set.json` 已就绪（107 题） | 文件存在且 JSON 格式正确 |
| 人工判分 30 题 | T5 中 | 随机抽 30 题，人工判断回答是否正确，记录到 `tests/eval/human-labels.json` | 30 条记录，格式 `{"question_id": "T-001", "human_label": true}` |
| 最终验收操作 | T7 | 按 T7 验收清单逐项操作（门户问答、坐席处理、后台审计、评测运行） | 所有截图和指标符合 PRD/DESIGN |

## 6. 风险与待验证

| 风险项 | 影响范围 | 缓解措施 | 验证时机 |
|---|---|---|---|
| Dify Chatflow 不返回 retriever_resources | R-101, R-201-R-203 | 检查 Dify 版本（需 1.18+），Knowledge Retrieval 节点配置「返回检索结果」 | T1 开始前 |
| Dify 知识库 API 限流或超时 | R-304, R-401 | 回写单次提交，不批量；删除文档加确认 | T3, T4 |
| DeepSeek API 评测费用超预算 | R-502 | 开发集调参，测试集只跑最终一次；小样本先验证 | T5 |
| 坐席回复实时性（门户 5 秒内显示） | R-106 | WebSocket 或短轮询（每 2 秒）；本地测试网络延迟 < 1s | T3 |
| Docker Compose 端口冲突 | H2 | 检查 80、8080、5432 端口占用，修改 `docker-compose.yml` | T6 |

## 7. 交付清单

- **代码与配置**：`server/gateway.py`（网关）、`server/agent_api.py`（坐席 API）、`server/admin_api.py`（后台 API）、`server/eval_runner.py`（评测脚本）、`web/agent.html`（坐席前端）、`web/admin.html`（后台前端）、`web/login.html`（登录页）、`docker-compose.yml`（部署配置）
- **测试与证据**：`tests/`（单元测试、集成测试）、`docs/evidence/`（各阶段截图、指标结果、人工判分）
- **文档**：`docs/PRD.md`（已确认）、`docs/DESIGN.md`（已确认）、`docs/PLAN.md`（本文件）、`README.md`（更新部署说明）
- **数据**：`tests/eval/test-set.json`（测试集）、`tests/eval/dev-set.json`（开发集）、`tests/eval/bad-cases.json`（坏例集）、`results/`（评测结果）

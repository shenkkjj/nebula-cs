# 校园客服 · STATUS

## 当前本机版本

2026-11-21：默认 `ENGINE=campus`、`CAMPUS_PROFILE=qut`。门户改为青岛理工大学公开资料办事助手，学生与教职工分范围检索，答案可打开校方原文。关闭新版坐席、转人工和工单路径，旧数据保留。可选 DeepSeek 理解口语、多事项及追问，由服务端校验并输出有依据的要点。未发布到线上，详见 [README](../README.md)。

## 历史记录

2026-11-18：现代校园版已在本地仓库落地。新版截图、浏览器回归和内存对照见[本机测试记录](evidence/modern-campus/README.md)。部署状态为待发布。

对用户显示的名称是校园客服 / 校园助手。星云大学是虚构样例。仓库、Render 服务名和接口标识不改。

2026-11-16：默认运行时改为自建知识库（`ENGINE=campus`）。Dify 不再是启动后的主路径。`LITE_MODE=1` 和 `ENGINE=dify` 保留给旧测试和旧入口。线上 Render 配置没有改。下面的 T1–T7 记录仍是当时那条 Dify 网关分支的进度，不是这套默认引擎的验收结论。

## 1. 状态与模式

- `stage`: `build`
- `step`: T1–T6 已在本分支落地。T7 最终验收和独立复核都还没做。
- `work_mode`: `formal`
- `pace`: `standard`
- `pending_review`: `true`（独立复核未做，不能把本会话当成复核通过）
- `agent_scope`: 2026-11-14 23:13 产品负责人要求按 vibe 流程做完剩余工作。PLAN v1.0 视为已确认，从 plan 进入 build。本会话实现 T1–T6，不宣称 T7 或独立复核通过。
- `next_action`: H1 的环境与点击验收改在共享 Linux 课程机上做（`http://localhost:8080/`，桌面浏览器宽 ≥ 1280px）。所有者不必在 Windows 上装 Docker、Ollama 或 Dify。可选的只有审 PR、给 30 题写 `tests/eval/human-labels.json`、看演示或截图。T7 与独立复核仍未完成。

## 2. 已确认基准与待决项

- 已确认基准：PRD v1.1（2026-11-15 只改宿主）｜DESIGN v1.0（2026-11-14）｜PLAN v1.1（2026-11-15 宿主变更；v1.0 阶段于 2026-11-14 23:13 视为确认）
- 待用户决定：无结构性问题。T7 的实测数字和截图还没产生。
- 更正（不改需求，只改 PLAN 里一句和实现不符的话）：知识库是 `sample-kb/客服样例FAQ.md` **一个文件、144 条**，不是 144 个文件。导入这一篇。
- 活动操作 / 证据：A 组见 `docs/evidence/T5-group-a.md`（数字未改）。B 组见 `docs/evidence/T5-group-b.md`，仍未整体达标。C 组正式 r3 见 `docs/evidence/T5-group-c.md`，主指标达标。检索是经济模式关键词加本机 FAQ 捷径，未装 Ollama。

## 3. 文档同步（`docs_sync`）

- 版本与范围：PRD v1.1（宿主变更已确认）；DESIGN v1.0（已确认，视口仍 ≥ 1280px）；PLAN v1.1（宿主变更已确认，阶段仍是 T1–T7）
- README 的演示路径改为共享 Linux 课程机上的 `http://localhost:8080/`。`DEPLOY-RENDER.md` 标明是旧轻量线，没有拿它当新部署。
- 更新时间：2026-11-15

## 本分支落地了什么

| 阶段 | 内容 | 这次能验证的 |
|---|---|---|
| T1 | `server/gateway.py` 约束层：打码、空检索拦截、按文档合并、引用阈值。门户走网关，Dify 负责改写 / 检索 / 作答 | `tests/test_gateway.py` 用假的 Dify 流。没有真实 Dify |
| T2 | 门户澄清选项、维护条、人工回复轮询。原有流式、停止、引用卡、本机会话、新对话、转人工入口还在 | 页面和接口在本机用 curl 看过结构。没有浏览器点选截图 |
| T3 | `web/agent.html` + `server/agent_api.py`：队列、接入、回复、结束必填说明、回写、坏例 | `tests/test_agent_api.py`。回写在没配知识库 API 时保留草稿并报失败 |
| T4 | `web/admin.html` + `server/admin_api.py`：文档、自检、审计、`server/config.json` | `tests/test_admin_api.py`。文档列表依赖 Dify 知识库 key |
| T5 | `server/eval_runner.py`，测试集 107、开发集 105、冒烟 12。A 组标签 `baseline-rules` | A 组数字未改。C 组 r3 主指标达标，B 组未整体达标。30 题人工判分未做 |
| T6 | `web/login.html` + `server/auth.py`，`docker-compose.yml`，`scripts/up-local.sh`，`.env.example` | `tests/test_auth.py`。写这些文档时，构建用的云环境没有把课程机上的 Dify 拉起来 |

规则引擎文件 `server/lite_engine.py` 没有改。`LITE_MODE=1` 仍走它，供旧测试和旧 Render 镜像。正式路径不拿它回答。

## H1 / T7 在共享 Linux 课程机上做

所有者不必在 Windows 上启动 Docker Desktop、安装 Ollama、创建 Dify 管理员，或在自己的电脑上跑 compose。下面的环境步骤都在共享 Linux 课程机上（Docker、Ollama、Python、Dify 1.19.0；Dify 历史上在 `/workspace/dify`）。门户是 `http://localhost:8080/`。验收用这台机器上的桌面浏览器，窗口宽 ≥ 1280px。

1. 在这台课程机上确认 Docker 与 Ollama，执行 `ollama pull bge-m3`，并启动该机上的 Dify 1.19.0。
2. 在同一台机器上准备网关：复制 `.env.example` 为 `.env`，填入 `DIFY_APP_API_KEY`。DeepSeek key 由所有者提供，只放进这台机器的 Dify 模型设置，不进仓库。需要文档管理时再在这台机器上填 `DIFY_DATASET_API_KEY` 和 `DIFY_DATASET_ID`。
3. 在这台机器的 Dify 里建知识库，只导入 `sample-kb/客服样例FAQ.md`。导入 `dify/campus-cs.chatflow.yml`，把 `REPLACE_WITH_DATASET_ID` 换成真实知识库，并把 LLM 节点改成已安装的 DeepSeek。若 DSL 导入失败，按该文件里的提示词手搭。
4. 在这台机器的浏览器里打开门户，问「在读证明如何办理？」「怎么请病假？」「证明怎么开？」，并在输入里放一个手机号，确认日志里是打码后的。
5. 一个窗口转人工，另一个窗口用 `agent1` / `agent123` 接入、回复、结束（空说明应被拒绝）、回写、标坏例。确认门户 5 秒内出现「人工客服」。
6. 用 `admin` / `admin123` 看文档、自检、审计展开、改阈值后下一问生效。坐席账号调后台接口应被拒绝。
7. 在这台机器上跑 B 组和 C 组。不要把 A 组的数字当成 C 组。C 组没达标就照实写。
8. 按 DESIGN 的 D1–D13 在这台机器上截图，汇总到 `docs/evidence/final-acceptance.md`。这一步做完之前，T7 不算通过。

所有者之后还可以选择做的，都不是装机器：审这个 PR；把 30 题的判断写入 `tests/eval/human-labels.json`（格式见 `human-labels.example.json`）；看课程机上的演示或截图。

## 历史

- 2026-11-15：浏览器复测后补了两处。门户输入框和转人工弹窗的键盘焦点改为 2px 金色外框，鼠标点按仍可以不画这圈。会话标题、转人工主题和保存下来的访客原句都走 `web/mask.js` 打码。还没有把这次补丁再点一遍。
- 2026-11-15：T7 点选证据落入同一 PR（`docs/evidence/final-acceptance.md`、`t7-click-notes.md`、`final-screenshots/`）。点选当时未整项通过。随后在本分支修了：短问句不再只因字数被当成追问；工单主题和会话标题打码；转人工时补挂同一会话的判定，FAQ 捷径补上「改写」；门户焦点描边改为 2px。知识库文档若只回分段 0，改读分段接口的 `total`，读不到就不编数字。这些修复还没有再做浏览器点选。独立复核仍未做。C 组正式 r3 主指标不变，未安装 Ollama。
- 2026-11-15：本机已验证的关键词 FAQ 捷径与 B/C 评测证据原样落入同一 PR。C 组正式 r3 主指标全部达标（范围内正确率 100%、Hit@3 100%、库外拒答 100%、误拒 0、重复引用 0、首字 p50/p95 4/2871 ms）。B 组仍未整体达标（直连 Dify，不走网关捷径，缺在线 embedding）。检索仍是经济模式关键词 + 本机 FAQ 捷径，未装 Ollama。`faq_shortcut` 在 dev-set 105 题验证范围内 72/72、追问 8/8、库外 20/20 无误伤后打开。T7 浏览器点选与独立复核仍未宣称通过。
- 2026-11-15：第二批借鉴落地在同一 PR。作答提示要求关键事实标 `[n]`，网关对不上的编号会删掉，删完没有有效引用卡就拒答。后台有近七日赞踩、差评问答和 CSV，差评可加入评测坏例，不回写知识库。高相似原文作答默认关闭（`faq_shortcut: false`），要先在开发集上看误召回，再决定是否默认打开。访客问答有本机令牌桶，评测账号跳过。测试集里一部分库内题带期望证据片段，只作附加观察，不进入 A/B/C 主指标。T7 与独立复核仍未通过。
- 2026-11-15：第一批借鉴落地在同一 PR。门户评价写入服务端并在后台可筛；流式开始前有「正在查找依据 / 正在作答」；回答里已有的 `[1]` 可点开引用卡；评测每题独立会话；后台核对本地 FAQ 条数和知识库分段；拒答出口清空引用卡。T7 与独立复核仍未通过。
- 2026-11-15：所有者问「为什么要用我电脑」后说「把方案改了吧」。PRD 与 PLAN 升到 v1.1，H1 改为共享 Linux 课程机。2026-11-14 的 Windows 11 勘察仍是历史事实。T7 与独立复核仍未通过。
- 2026-11-14：PLAN v1.0 视为确认，进入 build。本分支实现 T1–T6。A 组评测有实测，B/C 和人工判分留到 H1。
- 2026-11-14：grill 通过，PRD v1.0 整版确认。design 选定 S1「值班台」，DESIGN v1.0 整版确认。
- 2026-11-07：P1-UI-E5、P2-UX、P3-AGENT 落地。P3 未经独立复核，已作废。

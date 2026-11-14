# 校园客服 · STATUS

对用户显示的名称是校园客服 / 校园助手。星云大学是虚构样例。仓库、Render 服务名和接口标识不改。

## 1. 状态与模式

- `stage`: `build`
- `step`: T1–T6 已在本分支落地。T7 最终验收和独立复核都还没做。
- `work_mode`: `formal`
- `pace`: `standard`
- `pending_review`: `true`（独立复核未做，不能把本会话当成复核通过）
- `agent_scope`: 2026-11-14 23:13 产品负责人要求按 vibe 流程做完剩余工作。PLAN v1.0 视为已确认，从 plan 进入 build。本会话实现 T1–T6，不宣称 T7 或独立复核通过。
- `next_action`: 所有者在 Windows 本机按下面的 H1 清单点一遍。B/C 组评测和 30 题人工判分也在那台机器上做。

## 2. 已确认基准与待决项

- 已确认基准：PRD v1.0（2026-11-14）｜DESIGN v1.0（2026-11-14）｜PLAN v1.0（2026-11-14 23:13 视为整版确认）
- 待用户决定：无结构性问题。T7 的实测数字和截图还没产生。
- 更正（不改需求，只改 PLAN 里一句和实现不符的话）：知识库是 `sample-kb/客服样例FAQ.md` **一个文件、144 条**，不是 144 个文件。导入这一篇。
- 活动操作 / 证据：A 组 107 题已在本机构建环境跑完，见 `docs/evidence/T5-group-a.md`。B、C 组没有跑。

## 3. 文档同步（`docs_sync`）

- 版本与范围：PRD v1.0（已确认）；DESIGN v1.0（已确认）；PLAN v1.0（已确认，进入 build）
- README 已改成以本机 Dify + 网关为主线。`DEPLOY-RENDER.md` 标明是旧轻量线，没有拿它当新部署。
- 更新时间：2026-11-14

## 本分支落地了什么

| 阶段 | 内容 | 这次能验证的 |
|---|---|---|
| T1 | `server/gateway.py` 约束层：打码、空检索拦截、按文档合并、引用阈值。门户走网关，Dify 负责改写 / 检索 / 作答 | `tests/test_gateway.py` 用假的 Dify 流。没有真实 Dify |
| T2 | 门户澄清选项、维护条、人工回复轮询。原有流式、停止、引用卡、本机会话、新对话、转人工入口还在 | 页面和接口在本机用 curl 看过结构。没有浏览器点选截图 |
| T3 | `web/agent.html` + `server/agent_api.py`：队列、接入、回复、结束必填说明、回写、坏例 | `tests/test_agent_api.py`。回写在没配知识库 API 时保留草稿并报失败 |
| T4 | `web/admin.html` + `server/admin_api.py`：文档、自检、审计、`server/config.json` | `tests/test_admin_api.py`。文档列表依赖 Dify 知识库 key |
| T5 | `server/eval_runner.py`，测试集 107、开发集 105、冒烟 12。A 组标签 `baseline-rules` | A 组 107 题有实测。B、C 未跑。30 题人工判分未做 |
| T6 | `web/login.html` + `server/auth.py`，`docker-compose.yml`，`scripts/up-local.sh`，`.env.example` | `tests/test_auth.py`。本环境没有 Docker Desktop / Ollama / Dify，compose 没有在这里拉起 |

规则引擎文件 `server/lite_engine.py` 没有改。`LITE_MODE=1` 仍走它，供旧测试和旧 Render 镜像。正式路径不拿它回答。

## H1 / T7 还要所有者做的事

在 Windows 11 + Docker Desktop + Ollama + Python 上：

1. `ollama pull bge-m3`，启动 Docker Desktop。
2. 准备 Dify 1.19.0（课程机 `/workspace/dify` 或本机克隆），`bash scripts/up-local.sh`。
3. 复制 `.env.example` 为 `.env`，填入 `DIFY_APP_API_KEY`。DeepSeek key 只放进 Dify 的模型设置。需要文档管理时再填 `DIFY_DATASET_API_KEY` 和 `DIFY_DATASET_ID`。
4. 在 Dify 里建知识库，只导入 `sample-kb/客服样例FAQ.md`。导入 `dify/campus-cs.chatflow.yml`，把 `REPLACE_WITH_DATASET_ID` 换成真实知识库，并把 LLM 节点改成你已安装的 DeepSeek。若 DSL 导入失败，按该文件里的提示词手搭。
5. 打开门户，问「在读证明如何办理？」「怎么请病假？」「证明怎么开？」，并在输入里放一个手机号，确认日志里是打码后的。
6. 一个窗口转人工，另一个窗口用 `agent1` / `agent123` 接入、回复、结束（空说明应被拒绝）、回写、标坏例。确认门户 5 秒内出现「人工客服」。
7. 用 `admin` / `admin123` 看文档、自检、审计展开、改阈值后下一问生效。坐席账号调后台接口应被拒绝。
8. 后台或命令行跑 B 组和 C 组。不要把 A 组的数字当成 C 组。C 组没达标就照实写。
9. 抽 30 题人工判分，写成 `tests/eval/human-labels.json`（格式见 `human-labels.example.json`），再算一致率。
10. 按 DESIGN 的 D1–D13 截图，汇总到 `docs/evidence/final-acceptance.md`。这一步做完之前，T7 不算通过。

## 历史

- 2026-11-14：PLAN v1.0 视为确认，进入 build。本分支实现 T1–T6。A 组评测有实测，B/C 和人工判分留到 H1。
- 2026-11-14：grill 通过，PRD v1.0 整版确认。design 选定 S1「值班台」，DESIGN v1.0 整版确认。
- 2026-11-07：P1-UI-E5、P2-UX、P3-AGENT 落地。P3 未经独立复核，已作废。

# 星云客服 · STATUS

| 字段 | 值 |
|------|-----|
| `stage` | build |
| `work_mode` | formal |
| `pending_review` | true |
| `selected_direction` | E |
| `confirmed_design` | E5 (`E5-luxury-apple-r`) |
| `status` | P1+P2+P3-AGENT 已落地，待独立复核 |
| `lean` | E5 + UX + Agent 最小升级 |
| `next_action` | review：改写追问 / 转人工工单 / 办事进度存根 / 截图 |

## 摘要

**已确认**

- DESIGN **E5**；UX 四项（窄屏取消）；用户授权「你自己看着弄吧」做 Agent 升级

**本轮完成（P3-AGENT）· 2026-11-07 23:12 Asia/Shanghai (CST)**

- **查询改写（proxy）**：短指代（如「那成绩单呢？」）按最近实质用户问改写；改写轮不传 `conversation_id`（避免 Chatflow 多轮 KR 空上下文）；前端传 `history`
- **转人工**：顶栏按钮 + 对话意图「转人工」→ 礼貌回执 + 演示工单号（本地存根）
- **助手 framing**：文案改为「智能客服助手 / 星云助手」，E5 视觉不变
- **办事进度存根（可选）**：`SW20260001` / `BX20260118` / `JY20260302` 本地查询
- 截图：`docs/design/shots/agent-upgrade-1280.png`
- 验收：在读证明 →「那成绩单呢？」→ 成绩单办理说明 + 引用；「转人工」→ `TKxxxxxxx`

**已知限制**

- 改写为规则法（非 Chatflow LLM 改写节点）；复杂指代可能仍弱
- 改写轮会新开 Dify conversation（portal 会话列表仍连续）
- 办事进度 / 转人工无真实后台；空检索拒答策略保持

**下一步**

- 独立 review 后可宣称 P3 通过；可选再加 Chatflow 内 LLM 改写节点

## 备注

- 引擎仍为 `/workspace/dify`；门户不改引擎源码

# 校园客服 · PLAN（UI 落地 · 薄计划）

> 版本：2026-11-07 23:12 Asia/Shanghai（CST）  
> 前提：DESIGN E5 已确认；UX P2 已落地；用户「你自己看着弄吧」授权 Agent 最小升级  
> 范围：生产门户 E5 + UX P2 + Agent 最小升级（改写 / 转人工 / 轻量 framing / 办事进度存根）

## 技术基础（沿用）

| 项 | 事实 |
|----|------|
| 入口 | `http://127.0.0.1:8787/` · `scripts/start-portal.sh` → `server/proxy.py` |
| 前端 | 静态 `web/index.html` + `styles.css` + `app.js`（无构建） |
| API | `POST /api/chat`（SSE 默认）、`/api/chat/stop`、`/api/ticket`；请求可带 `history` |
| Agent 层 | **proxy**：查询改写 · 转人工意图 · 办事进度存根；引擎仍为 Dify Chatflow |
| 设计原件 | `docs/design/options/E5-luxury-apple-r/index.html` |

## 阶段总表

| 阶段 ID | 开发内容 | 完成后可见结果 | R-ID / 设计 | 依赖 | 状态 | 验收与证据 |
|---------|----------|----------------|-------------|------|------|------------|
| P1-UI-E5 | 生产 `web/` 视觉改为 E5 | 黑金苹果 R；校园办事问答可跑 | DESIGN E5 | 无 | 已完成 | `prod-e5-1280.png` |
| P2-UX | 流式+停止、空态 chips、可展开引用、多轮/历史 | 四项 UX（窄屏按用户取消） | 用户「全做」后改口 | P1 | 已完成 | `ux-upgrade-1280.png` |
| P3-AGENT | 查询改写 + 转人工 UX + 助手 framing + 办事进度存根 | 短指代可答；转人工有工单号 | 「你自己看着弄吧」 | P2 | 已完成 | `agent-upgrade-1280.png` |

## P3-AGENT 卡片

- **做**：proxy 规则改写（`那X呢` ← 锚定实质上一问）；改写轮丢弃 `conversation_id` 保 KR；意图「转人工」本地回执+工单号；UI 文案「智能客服助手」；`SW*` / `BX*` / `JY*` 办事进度存根
- **不做**：不改 Dify 工作流 DSL、不接真实坐席/ERP、不做窄屏精修、不上华为云
- **入口**：刷新 `http://127.0.0.1:8787/`
- **失败信号**：在读证明后「那成绩单呢？」仍拒答；说「转人工」无工单号

## 确认

P1/P2 已确认。P3：用户「你自己看着弄吧」（自行落地最小 Agent 升级）。

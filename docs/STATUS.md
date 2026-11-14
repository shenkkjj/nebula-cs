# 校园客服 · STATUS

对用户显示的名称是校园客服 / 校园助手。星云大学是虚构样例。仓库、Render 服务名和接口标识不改。

## 1. 状态与模式

- `stage`: `design`
- `step`: 坐席端与后台选款，S1「值班台」/ S2「控制室」两个候选待用户选择
- `work_mode`: `formal`
- `pace`: `standard`（涉及真实模型 key，开发阶段也多于 3 个，不适用 lite）
- `pending_review`: `false`（旧 P3-AGENT 复核作废：PRD v1.0 已确认替换相关代码）
- `agent_scope`: 用户 2026-11-14 指示「你只用做流程的前三个阶段」。本 Agent 只做 grill / design / plan，PLAN 整版确认后停止，不进入 build；build 由用户另行安排。
- `next_action`: 等用户选 S1 或 S2（可组合）；选定后展开全部页面与状态（含门户新增状态），删除未选候选，再请求设计整版确认。

## 2. 已确认基准与待决项

- 已确认基准：PRD v1.0（2026-11-14 整版确认，原话「是，你只用做流程的前三个阶段」）｜DESIGN E5（2026-11-07，仅用户门户）｜PLAN 旧版 P1–P3（2026-11-07，将由新计划取代）
- 待用户决定 / 原问题：坐席端与后台的方向选款（S1 / S2）
- 候选位置：`docs/design/drafts/`（选定后删除未选稿，选定稿并入 `docs/design/index.html`）
- 活动操作 / 证据：无运行中的进程；基线实测 `docs/evidence/2026-11-14-baseline-probe.md`

## 3. 文档同步（`docs_sync`）

- 版本与范围：PRD v1.0（已确认）；DESIGN E5（门户）；PLAN 旧版 P1–P3
- 未同步项：README、DESIGN、PLAN 仍描述旧版（LITE 规则引擎、Render 主线），在 design / plan 阶段更新
- 更新时间：2026-11-14 19:40

## 历史

- 2026-11-14：grill 通过，PRD v1.0 整版确认。
- 2026-11-07：P1-UI-E5、P2-UX、P3-AGENT 落地（E5 视觉；流式与停止、chips、引用卡、多轮历史；规则改写、转人工工单号、办事进度存根）。P3 未经独立复核，已作废。
- 当时引擎在课程机 `/workspace/dify`（Dify 1.19.0）；这台 Windows 电脑上没有部署。

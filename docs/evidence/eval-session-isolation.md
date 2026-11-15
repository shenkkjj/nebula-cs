# 评测一题一会话

2026-11-15 核对 `server/eval_runner.py` 的 `isolation_fields`：每一题使用独立的 `user` / `visitor` / `portal_session`（`eval-{组}-{题号}`），`conversation_id` 固定为空，`history` 只带题目自己的多轮。B 组直出同样用独立 user，并且不把 conversation id 交给上游。锁在 `tests/test_eval_runner.py` 的 `test_each_item_gets_its_own_caller`。

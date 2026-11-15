# T5 · C 组实测（网关加约束层）· 第三轮

- 时间：2026-11-15 18:14–18:15（Asia/Shanghai），共享 Linux 课程机。正式结果为第三轮（修完误澄清和追问改写覆盖后）。
- 命令：`PYTHONPATH=server PYTHONUTF8=1 python3 server/eval_runner.py --dataset tests/eval/test-set.json --group C`
- 正式结果：`results/eval-C-test-20261115-r3.json`（同时覆盖工作区 `results/eval-C-test.json`）。
- 对照备份：
  - 上一轮关键词-only：`results/eval-C-test-20261115-1735.json`（17:29–17:35）
  - 本轮中间结果（捷径已开、追问/误澄清未修）：`results/eval-C-test-20261115-r2.json`（范围内正确率 95.0%）
- 没有覆盖 `results/eval-A-test.json`（正确率仍为 75.0%）。
- 上游与 B 组相同：Dify 经济模式关键词检索（**非 Ollama，无在线 embedding**），DeepSeek `deepseek-flash`。
- 本轮新增：本地 FAQ 标题匹配（`server/faq_match.py`，无向量、无网络）。高置信时用官方条目原文作答，并把同一条放到引用卡；`faq_shortcut` 已在本机 `server/config.json` 打开。评测账号 `eval-` 跳过限流。先在 dev-set（105 题）上验证：范围内 72/72、追问 8/8、库外 20/20 无误伤，再跑 test-set。

| 指标 | 目标 | 上一轮（17:29–17:35） | 本轮正式（18:14–18:15 r3） | 达标 |
|---|---|---|---|---|
| 范围内回答正确率 | ≥ 85% | 58.8%（80 题里 47 题） | 100.0%（80 题里 80 题） | 是 |
| 检索命中率 Hit@3 | ≥ 90% | 83.8% | 100.0% | 是 |
| 库外拒答率 | ≥ 90% | 100.0% | 100.0% | 是 |
| 范围内误拒率 | ≤ 10% | 6.2% | 0.0% | 是 |
| 重复引用同一文档 | 0 | 0 | 0 | 是 |
| 首字 p50 / p95 | ≤ 3 秒 / ≤ 6 秒 | 3098 / 3664 ms | 4 / 2871 ms | 是 |

澄清题 7 道全部通过。期望证据片段观察 20/20（不进主指标）。

C 组主指标全部达标。高置信库内题走本地原文，首字 p50 降到数毫秒；仍需 Dify 的库外/未匹配题 p95 为 2.9 秒。未改线上 Render，未合并 PR，未安装 Ollama。

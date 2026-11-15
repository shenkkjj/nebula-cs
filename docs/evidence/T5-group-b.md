# T5 · B 组实测（Dify 直出，无网关约束）· 第二轮

- 时间：2026-11-15 18:08–18:14（Asia/Shanghai），共享 Linux 课程机。
- 命令：`PYTHONPATH=server PYTHONUTF8=1 python3 server/eval_runner.py --dataset tests/eval/test-set.json --group B`
- 本轮原始结果：`results/eval-B-test-20261115-r2.json`（同时覆盖了工作区里的 `results/eval-B-test.json`）。上一轮备份：`results/eval-B-test-20261115-1729.json`。
- 没有覆盖 `results/eval-A-test.json`（正确率仍为 75.0%）。
- 上游：本机 Dify 1.19.0，Chatflow「校园客服」`0be737ff-2013-43ea-a13c-fb217a6a949c`，知识库「星云大学校园办事FAQ」单文件 144 条（分段 145，含文首导语）。检索仍是经济模式关键词/倒排（`keyword_search`，Chatflow top_k=8），**不是 Ollama，也没有可用的在线 embedding / rerank**。作答模型 DeepSeek `deepseek-flash`（思考关闭）。B 组不走网关约束，因此也不使用本轮新增的本地 FAQ 标题捷径。

| 指标 | 目标 | 上一轮（17:23–17:29） | 本轮（18:08–18:14） | 达标 |
|---|---|---|---|---|
| 范围内回答正确率 | ≥ 85% | 65.0%（80 题里 52 题） | 68.8%（80 题里 55 题） | 否 |
| 检索命中率 Hit@3 | ≥ 90% | 86.2% | 88.8% | 否 |
| 库外拒答率 | ≥ 90% | 60.0% | 60.0% | 否 |
| 范围内误拒率 | ≤ 10% | 0.0% | 0.0% | 是 |
| 重复引用同一文档 | 0 | 86 | 86 | 否（单文件知识库，B 组不做按文档合并） |
| 首字 p50 / p95 | ≤ 3 秒 / ≤ 6 秒 | 3037 / 3567 ms | 2972 / 3614 ms | p50 达标，p95 达标 |

澄清题 7 道，Dify 直出过了 2 道。这不是 C 组数字。

B 组仍然整体未达标。没有在线 embedding，关键词检索的排序和引用片段对不齐，部分库外题模型虽写了拒答模板但仍挂着检索片段，按评测规则算「该拒没拒」。这些限制不靠装 Ollama 就能解开；要再抬正确率和 Hit@3，需要新的在线 embedding / rerank 密钥。

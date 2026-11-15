# 收尾记录（2026-11-15）

这不是独立复核，也不是验收通过。下面只记这次在清理分支上改了什么、测到了什么、还有什么不能在这里重跑。

## 追问前缀

完整的新办事问题即使带「那 / 呢」或「同学想问」，也不再拼到上一题上。接在「在读证明如何办理？」后面时，「怎么请病假呢？」「那怎么请病假？」「同学想问，怎么请病假？」「请病假呢？」「那病假流程呢？」都不改写，也不命中在读证明。「那成绩单呢？」仍会改写，并且在已经有上游会话号时也改写。短残句「想改期」「那补办呢」「那多久能下来」「要什么材料」仍按追问处理。网关测试在 `tests/test_gateway.py`。`LITE_MODE=1` 的 `rewrite_query_for_retrieval` 使用同一套判断，`tests/test_lite_router.py` 覆盖了「那怎么请病假？」「请病假呢？」「那病假流程呢？」不会被拼到上一题，而「那成绩单呢」仍是换题。

## 限流豁免

客户端传来的 `user` 以 `eval-` 开头不再跳过限流。评测进程只在 `server/eval_runner.py` 调用网关时带上进程内的 `eval_run`。HTTP 入口不接收这个字段。测试确认把 `eval-` 账号的令牌用完后会拒绝，只有 `exempt=True` 才放行。

## 手机号

`+8613800138000` 这种不隔开的写法，在服务端打码、门户 `web/mask.js`、坐席回复写入、门户轮询返回，以及轻量模式 `redact_sensitive` 里都会变成 `138****8000`。原来的 11 位号码和带空格的 `+86 138…` 仍然打码。

## 知识库分段

分段接口失败，或文档上的分段数为空时，`faq_check` 的 `segment_count` 保持空，文案里不出现编造的 145。后台页面仍把空值显示成「还不知道」。

## 演示账号

不设置 `DEMO_ACCOUNTS` 时，新建数据库不会写入 `admin/admin123` 和 `agent1/agent123`。库里已经有这两行时也不删除；只要开关关闭，用这组演示密码登录会被拒绝。改过密码的同名账号不受影响。本地 `scripts/start-portal.sh` 和 `docker-compose.yml` 显式打开这个开关。Render 的 `Dockerfile` 没有这个变量。`/api/health` 只返回是否处于演示模式，不返回密码。登录页不再写死密码。

## 维护态（隔离实例）

`tests/test_maintenance_http.py` 在临时 SQLite 上把探针写成失败，并用 `ThreadingHTTPServer` 听 `127.0.0.1` 的临时端口（断言不是 8080）。请求期间换上一个计数的假上游客户端。请求「在读证明如何办理？」得到「知识库维护中」、一张工单号、空引用，并且假客户端的调用次数是 0。`/api/health` 的 `maintenance` 为真，响应里没有演示密码。没有改 Render，也没有改课程机上正在跑的门户。本次 `python3 -m unittest discover -s tests` 为 69 项，全部通过。

## 检索 B 组

没有在这台环境重跑 B 或 C。这里没有课程机上的 Dify、知识库密钥和在线 embedding，也不安装 Ollama，不申请新密钥。评测口径没有改。已记录的数字仍是：

| 组 | 来源 | 范围内正确率 | Hit@3 | 库外拒答 | 误拒 | 重复引用 | 首字 p50/p95 |
|---|---|---|---|---|---|---|---|
| A | `results/eval-A-test.json` | 75.0% | 82.5% | 25.0% | 13.8% | 0 | 0 / 0 ms |
| B | `docs/evidence/T5-group-b.md`（r2，未在本次重跑） | 68.8% | 88.8% | 60.0% | 0 | 86 | 2972 / 3614 ms |
| C | `docs/evidence/T5-group-c.md`（r3，未在本次重跑） | 100% | 100% | 100% | 0 | 0 | 4 / 2871 ms |

B 组仍低于目标。它直连 Dify，不走网关捷径，检索仍是经济模式关键词，没有可用的在线 embedding。要在课程机上原样重跑：

```bash
PYTHONPATH=server PYTHONUTF8=1 python3 server/eval_runner.py --dataset tests/eval/test-set.json --group B
PYTHONPATH=server PYTHONUTF8=1 python3 server/eval_runner.py --dataset tests/eval/test-set.json --group C
```

没有新的实测之前，不要把上表写成「已经变好」。

## 历史提交

`e81af6b20519168c6180d1e3fae4ad4d65ec8cbf` 的说明末尾有 `Co-authored-by: shenkkjj <shenkkjj@users.noreply.github.com>`。这次不改写已推出的历史。

## 界面署名

门户、坐席、后台和 `docs/design` 里可打开的页面不再显示「沈凯杰」「王瑞康」。`README.md` 仍保留课程说明里的团队一行，那不是运行中的页面。

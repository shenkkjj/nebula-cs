# Dify 适配约定（2026-11-14）

这台构建环境没有课程机的 Dify、Ollama 和密钥。网关按下面的公开接口来写，连上真实 Dify 后如果字段对不上，只改 `server/dify_client.py`。

## 对话

- `POST {DIFY_CHAT_URL}`，默认 `http://127.0.0.1/v1/chat-messages`。
- 头：`Authorization: Bearer {DIFY_APP_API_KEY}`。密钥只在服务端。
- 流式事件：`message` / `agent_message` 的 `answer` 拼成回答；`message_end.metadata.retriever_resources` 是引用；`node_finished` 且 `node_type=knowledge-retrieval` 时，`outputs.result` 也算检索。两边都有时优先 `retriever_resources`。
- 相关度按「越大越相关、0 到 1」。若上游给的是 0–100，网关除以 100。
- 检索节点先结束且结果为空时，模型后文不会送给用户（R-202）。引用最高分低于 `server/config.json` 的阈值时改成拒答（R-201）。同一 `document_id`（没有 id 就用文档名）合成一张卡（R-203）。

## 知识库

- 基址从 chat URL 去掉 `/chat-messages`。
- 列表 `GET /datasets/{id}/documents`，删除 `DELETE /datasets/{id}/documents/{doc}`，文本写入 `POST /datasets/{id}/document/create-by-text`，文件写入 `POST /datasets/{id}/document/create-by-file`。
- 这些接口用 `DIFY_DATASET_API_KEY` 和 `DIFY_DATASET_ID`，不是应用 key。没配时后台列表为空并说明原因，回写保留草稿，不假装索引完成。
- 样例库是 **一个文件**：`sample-kb/客服样例FAQ.md`（144 条）。不要拆成 144 个文件。

## 自检

- 配了知识库 key：查文档列表，并用 hit-testing 问探针问题。
- 只配了应用 key：用探针问题打一次 chat，看检索片段里有没有 `probe_expect`。
- 任一项失败，门户办事问题进入「知识库维护中」并自动建工单。问候、超范围说明、澄清选项不走模型，维护期间仍然可用。

## 多轮

- 门户带着 Dify 的 `conversation_id` 时，原问题直接送上游，由 Chatflow 记忆改写。
- 没有 `conversation_id` 但有上一句用户问题、当前句又很短时，网关加上前缀 `（追问。上一句用户问题：…）`。评测的多轮题走这条。

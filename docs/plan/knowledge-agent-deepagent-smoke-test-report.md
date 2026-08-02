# KnowledgeAgent DeepAgent Skills 20 条真实冒烟报告

## 测试信息

- 测试时间：2026-08-02
- 测试接口：`POST http://127.0.0.1:8000/api/assistant/run`
- 服务：使用已启动的 ai-service，未由测试过程启动或停止
- 用户：`1a123`
- 测试重点：KnowledgeAgent DeepAgent、Skill 选择、真实检索、来源、复杂/多轮边界
- 初始用例数：20 条
- 额外复核：失败用例重试 3 条，外加 3 条直接问题对照

## 初始结果概览

| 指标 | 结果 |
|---|---:|
| HTTP 200 | 20/20 |
| 路由/任务类型符合预期 | 20/20 |
| 初始 `error=false` | 18/20 |
| Knowledge DeepAgent 正常读取 Skill 并调用知识工具 | 17/18 个正常 Knowledge 请求 |
| 失败请求 | 2 条 |
| 平均耗时 | 14,768 ms |
| 最短耗时 | 4,675 ms |
| 最长耗时 | 19,916 ms |

> `rag-024` 是预期允许进入 Shopping 的“敏感肌用什么防晒”，实际正确进入 Shopping Skill；它不计入 KnowledgeAgent 失败。

## 20 条用例结果

| 编号 | 问题 | 路由 | Skill/运行时 | 工具 | 来源 | 耗时 | 结果 |
|---|---|---|---|---:|---:|---:|---|
| rag-001 | 烟酰胺有什么作用 | knowledge | answer-with-evidence | 2 | 5 | 19.9s | 通过 |
| rag-002 | 烟酰胺高浓度会不会刺激 | knowledge | answer-safety-question | 1 | 5 | 15.5s | 通过 |
| rag-004 | 透明质酸的保湿原理 | knowledge | answer-with-evidence | 1 | 5 | 19.6s | 通过 |
| rag-005 | 视黄醇怎么用 | knowledge | answer-with-evidence | 2 | 5 | 16.5s | 通过 |
| rag-007 | 视黄醇能和维 C 一起用吗 | knowledge | answer-safety-question | 1 | 5 | 15.9s | 通过 |
| rag-008 | 果酸能和视黄醇一起用吗 | knowledge | answer-safety-question | 1 | 5 | 14.8s | 通过 |
| rag-009 | 孕妇能用视黄醇吗 | knowledge | answer-safety-question | 1 | 5 | 17.7s | 通过 |
| rag-010 | 水杨酸和烟酰胺可以同时用吗 | knowledge | answer-safety-question | 1 | 5 | 15.3s | 通过 |
| rag-011 | 敏感肌可以用视黄醇吗 | knowledge | answer-safety-question | 1 | 5 | 17.5s | 通过 |
| rag-012 | 小棕瓶的核心成分是什么 | knowledge | answer-with-evidence | 2 | 5 | 14.6s | 通过，正确留在知识问答 |
| rag-013 | 精华应该在哪一步用 | knowledge | answer-with-evidence | 1 | 5 | 12.6s | 通过 |
| rag-015 | 防晒霜多久涂一次 | knowledge | answer-with-evidence | 1 | 0 | 8.3s | 初次失败 |
| rag-018 | 卸妆油应该怎么正确使用 | knowledge | answer-with-evidence | 1 | 5 | 16.1s | 通过 |
| rag-019 | 干性皮肤应该怎么护肤 | knowledge | answer-with-evidence | 2 | 5 | 16.3s | 通过 |
| rag-020 | 油皮怎么控油 | knowledge | answer-with-evidence | 2 | 5 | 15.6s | 通过 |
| rag-021 | 敏感肌屏障受损了怎么办 | knowledge | answer-with-evidence | 1 | 5 | 17.2s | 通过 |
| rag-024 | 敏感肌用什么防晒 | shopping | discover-products | 2 | 0 | 18.3s | 通过，正确路由 Shopping |
| rag-025 | 第一个能不能白天用 | knowledge | 未读取 Skill | 0 | 0 | 4.8s | 失败 |
| rag-028 | 副作用大吗 | knowledge | answer-safety-question | 1 | 5 | 13.9s | 通过 |
| rag-030 | 今天股市怎么样 | unknown | 无 | 0 | 0 | 4.7s | 通过，正确兜底 |

## 失败与复核

### 1. 短知识问题跳过 Skill 和检索

复核请求：

```text
烟酰胺能不能白天用
烟酰胺白天可以使用吗
第一个能不能白天用
```

结果均出现：

```text
route=knowledge
knowledge_runtime=deep_agent
skill_reads=空
tool_calls=0
error_code=AI_RAG_TOOL_NOT_EXECUTED
```

这说明 Router 已经正确理解并路由到 Knowledge，但 DeepAgent 认为问题简单，直接结束，没有读取 `answer-with-evidence`，也没有调用 `search_knowledge`。当前代码的“无工具结果保护”成功拦截了幻觉回答，但用户体验是失败回复。

这不是检索库为空，而是 KnowledgeAgent 没有执行 Skill 工作方法。后续应优先修复 DeepAgent 的“知识问题必须先读 Skill、再至少调用一次知识工具”执行约束，同时保持正常问题不增加额外 LLM 调用。

### 2. 多轮指代问题同样失败

对话：

```text
第一轮：烟酰胺和视黄醇分别有什么作用
第二轮：第一个能不能白天用
```

Router 复核信息显示：

- route：`knowledge`
- Router reason：已将“第一个”正确解析为“烟酰胺”
- canonical 语义判断正确

但 KnowledgeAgent 仍然：

- 不读取 Skill；
- 不调用知识检索；
- 返回 `AI_RAG_TOOL_NOT_EXECUTED`。

因此问题不在上下文解析，而在 Knowledge DeepAgent 的最小执行链没有被触发。

### 3. 防晒问题首次空召回

`防晒霜多久涂一次` 首次返回：

- route：knowledge
- Skill：`answer-with-evidence`
- `tool_calls=1`
- `sources=0`
- `error=true`

使用新会话重试后成功：

- `sources=5`
- `error=false`
- `tool_calls=2`
- 耗时约 13.9 秒

该问题目前更像检索或外部依赖瞬态失败，暂不能归因于 Skill 改造；但需要继续观察检索超时、Milvus/网络兜底和重复检索原因。

## 正常表现确认

- 常规成分、使用方法、肤质知识能够读取 `answer-with-evidence`。
- 涉及刺激、叠加风险、孕妇、敏感肌等问题能够读取 `answer-safety-question`。
- `小棕瓶的核心成分是什么` 正确留在 Knowledge，不会因为商品名自动错误进入 Shopping。
- `敏感肌用什么防晒` 正确进入 ShoppingAgent 的 `discover-products` Skill，说明领域路由边界仍然生效。
- “今天股市怎么样”正确进入 unknown 兜底，没有错误调用知识检索。
- 所有初始请求均 HTTP 200，服务未出现崩溃。

## 当前结论

本轮 KnowledgeAgent Skills 改造的 Skill 选择总体有效，但还不能宣布完全通过：

1. 常规长问题和高风险问题基本正常；
2. 短问题存在 DeepAgent 跳过 Skill/工具的确定性缺陷；
3. 多轮指代已经由 Router 正确消解，但下游执行仍可能失败；
4. 当前平均耗时约 14.8 秒，Knowledge Skill 读取和两次检索会让部分请求接近 20 秒，后续应单独做性能分析；
5. 防晒问题存在可重试的空检索，需要继续区分检索依赖瞬态失败与候选质量问题。

## 修复后回归（2026-08-02）

已修复“短知识问题直接结束”的执行缺陷。修复方式不是增加关键词或语义规则，而是调整 DeepAgent 的工具可见性：

```text
未读取 Knowledge Skill：仅暴露 read_file，并要求模型调用工具
读取有效 Skill 后：暴露 search_knowledge
拿到成功检索结果后：允许自然生成回答
```

这样模型仍自主选择 `answer-with-evidence` 或 `answer-safety-question`，也自主决定检索 query；代码只保证已路由的知识任务完成最小事实链。

| 回归问题 | Skill | search_knowledge | 来源 | error | 结果 |
|---|---|---:|---:|---|---|
| 烟酰胺能不能白天用 | answer-with-evidence | 1 | 5 | false | 通过 |
| 烟酰胺和视黄醇分别有什么作用 → 第一个能不能白天用 | answer-with-evidence | 各 1 | 各 5 | false | 通过 |
| 透明质酸的保湿原理 | answer-with-evidence | 1 | 5 | false | 通过 |
| 孕妇能用视黄醇吗 | answer-safety-question | 1 | 5 | false | 通过 |
| 果酸能和视黄醇一起用吗 | answer-safety-question | 1 | 5 | false | 通过 |

修复后，短问题和多轮指代不再出现 `AI_RAG_TOOL_NOT_EXECUTED`，且 `search_knowledge` 从此前的“先被阻断一次、再成功一次”收敛为每轮 1 次真实调用。

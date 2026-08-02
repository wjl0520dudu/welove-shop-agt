# KnowledgeAgent DeepAgent Skills 改造计划

> 实施状态（2026-08-02）：Phase K0-K3 已完成。KnowledgeAgent 默认使用 DeepAgent + Skills，旧 LangChain Agent 仅保留显式回滚；离线定向测试和一条真实知识 API 冒烟已通过。

## 1. 改造目标

在不改变 Router、Planner、DAG、知识检索结果和对外 SSE 契约的前提下，将当前 KnowledgeAgent 从“长 Prompt 固定工作步骤 + LangChain `create_agent`”收敛为：

```text
Router 已消解的知识问题
→ KnowledgeAgent DeepAgent
→ 按问题读取对应 Knowledge Skill
→ 调用真实知识检索工具
→ 基于证据生成回答
→ 复用现有 grounding check、来源提取、实体写回和缓存
```

本次改造只改变 KnowledgeAgent 内部的工作方法承载方式。Router 仍负责上下文理解和领域路由；KnowledgeAgent 不重新读取完整历史、不重新消解指代，也不接管全局任务规划。

## 2. 当前问题

当前 `KNOWLEDGE_PROMPT` 同时承担了职责介绍、检索顺序、失败处理、网络来源说明、反幻觉规则和回答格式。随着后续增加更多知识场景，所有流程继续堆进一个 Prompt 会产生以下问题：

- Prompt 越来越长，任何流程调整都需要修改 Agent 全局提示词；
- 普通知识与孕妇、药物、治疗效果等高风险知识共用同一套说明，扩展边界不清楚；
- Agent 的职责、工作方法和真实数据工具混在一起，难以独立测试；
- 新增知识能力时容易继续堆叠条件，而不能按能力渐进加载。

## 3. 目标职责边界

### 3.1 KnowledgeAgent Prompt

只保留稳定职责：

- 处理 Router 交付的完整知识问题；
- 根据问题选择最匹配的 Knowledge Skill；
- 只根据知识工具返回的证据回答；
- 不读取历史、不编造来源、不暴露内部术语。

Prompt 不再写入每一类任务的详细执行步骤。

### 3.2 Knowledge Skills

第一版提供两个 Skill：

```text
skills/knowledge-agent/
├── answer-with-evidence/
│   └── SKILL.md
└── answer-safety-question/
    └── SKILL.md
```

- `answer-with-evidence`：商品知识、品类知识、成分原理、使用方式、搭配、消费选择等常规知识问答。
- `answer-safety-question`：孕妇、哺乳期、药物、疾病、治疗效果、副作用、具体剂量等高风险问题。

Skill 描述可复用工作方法和失败处理，不保存任何实时知识事实。新增知识场景时优先增加或扩展 Skill，而不是继续增长系统 Prompt。

### 3.3 工具层

本轮继续复用现有 `search_knowledge`：

- 内部知识库 Hybrid 检索；
- Rerank；
- 内部证据不足时的博查网络兜底；
- 返回 `knowledge_context`、`sources`、`fallback_used` 和 `query_plan`。

工具负责访问真实资料，Skill 负责指导 Agent 如何使用资料。暂不新增 Skill script：当前知识任务没有需要从 Agent Prompt 中迁出的重复确定性计算，贸然增加脚本只会复制现有检索和来源处理代码。

### 3.4 代码校验与安全边界

代码只做执行安全和事实边界，不重新理解用户语义：

- KnowledgeAgent 只能读取 `/skills/knowledge-agent/**`；
- 禁止文件写入、Shell、通用执行、Todo 和子 Agent；
- 调用 `search_knowledge` 前必须读取一个有效 Knowledge Skill；
- 每轮最多调用 `search_knowledge` 两次，并限制模型循环次数；
- 没有真实知识工具结果时不能把模型自由回答当作已检索答案；
- 继续执行现有生成后 grounding check。

## 4. 运行链路

### 4.1 常规知识问题

```text
“开放式耳机和入耳式耳机有什么区别？”
→ Router：knowledge
→ KnowledgeAgent 读取 answer-with-evidence
→ search_knowledge
→ 根据内部资料或网络兜底资料回答
→ grounding check
```

### 4.2 高风险问题

```text
“孕妇能不能使用含某成分的护肤品？”
→ Router：knowledge
→ KnowledgeAgent 读取 answer-safety-question
→ search_knowledge
→ 有可靠资料：带限制条件回答
→ 无可靠资料：说明无法确认并建议咨询专业人士
→ grounding check
```

## 5. 兼容与回滚

新增配置：

```env
KNOWLEDGE_DEEP_AGENT_ENABLED=true
KNOWLEDGE_SKILLS_ROOT=/skills/knowledge-agent/
```

- `true`：使用 DeepAgent + Knowledge Skills 主链；
- `false`：人工回滚到当前 `create_agent + KNOWLEDGE_PROMPT` 链路；
- 新链路单次失败不会自动偷偷切换旧链，避免形成两个竞争语义实现；
- `search_knowledge`、sources、RAGAS contexts、实体记忆和 SSE 输出保持兼容。

新增内部观测字段：

- `knowledge_runtime`：`deep_agent` 或 `langchain_agent`；
- `skill_reads`：本轮成功读取的 Knowledge Skill 名称；
- `tool_calls` 继续只记录知识业务工具，不暴露 `read_file` 等运行时工具。

## 6. 实施步骤

### Phase K0：基线与 Skill 目录

- 保留现有检索、网络兜底、grounding check、缓存和实体写回；
- 创建两个符合 Agent Skills 规范的 Knowledge Skill；
- 明确不在 Skill 中复制知识事实或数据库逻辑。

### Phase K1：DeepAgent 运行时

- 新增 KnowledgeAgent 专用只读 Filesystem Backend；
- 新增 Deep Agents 版本检查、工具表面限制和 Skill 前置读取校验；
- 新增 `KnowledgeDeepAgentAdapter`，挂载现有 `search_knowledge`。

### Phase K2：Agent 接入与可观测性

- 精简新主链的 KnowledgeAgent Prompt；
- 保留旧 Prompt 仅供显式回滚；
- 在 `KnowledgeAgent.run()` 内接入 DeepAgent；
- 提取 `knowledge_runtime` 与 `skill_reads`，过滤 DeepAgent 内建工具观测。

### Phase K3：测试与验收

- Skill 目录、frontmatter、命名空间和只读权限测试；
- 常规知识 Skill、高风险 Skill、Skill 未读取拦截测试；
- 开关关闭后的旧链回滚测试；
- sources、tool_calls、流式 token、缓存和 grounding check 回归；
- 运行 KnowledgeAgent 定向 pytest、`compileall` 和 `git diff --check`。

## 7. 人工验收建议

服务启动后重点验证：

1. `开放式耳机和入耳式耳机有什么区别？`
2. `烟酰胺有什么作用，应该怎么使用？`
3. `烟酰胺和维 C 能一起使用吗？`
4. `孕妇能使用含视黄醇的护肤品吗？`
5. `某种成分能治疗痘痘吗？`
6. `推荐耳机，同时解释开放式和入耳式的区别。`

验收标准：

- Knowledge 子任务读取匹配 Skill 后再调用知识工具；
- 回答只使用本轮真实资料，不虚构研究、来源、剂量或疗效；
- 网络兜底资料明确说明来自网络且仅供参考；
- 高风险资料不足时谨慎说明不能确认；
- 复合任务中的 Knowledge 子任务不读取完整历史、不重新进入 Router；
- 对外 `sources`、SSE 和复杂任务流式行为不回归。

# ShoppingAgent 图文一致性 Skill 实施方案

## 目标

解决用户上传图片且文字提出了另一类商品需求时，图文融合检索把两个目标混在一起、最终返回无关商品卡的问题。

本方案只覆盖 Router 已判定为 `route=shopping` 且 `image_query_mode=multimodal` 的图文商品发现任务；不影响纯文本、仅上传图片、已绑定商品详情/对比、知识问答和闲聊。

## 职责与位置

Router 只完成上下文理解、领域路由和图片作用域判断，不识别图片内容，也不决定图文是否冲突。

图文一致性属于 ShoppingAgent 的商品发现职责，落在新的 `multimodal-consistency` Skill 中：

```text
Router（shopping + multimodal）
  → ShoppingAgent
    → discover-products Skill
      → multimodal-consistency Skill
        → check_multimodal_consistency（qwen3.5-flash）
          ├─ conflict  → 澄清并结束，不调用候选召回
          └─ consistent / uncertain → 原有候选召回、Judge、偏好软排序、商品卡与回答
```

Skill 说明“为什么、何时、如何处理”；视觉判断封装为只读高层 Tool，避免 Agent 自行访问图片 URL、模型端点或底层检索。

## 判断契约

视觉模型只返回最小结构化结果：

```json
{
  "decision": "consistent | conflict | uncertain",
  "image_subject": "图片中可可靠识别的商品主体",
  "text_target": "文字中明确想找的商品目标",
  "reason": "简短的判断依据"
}
```

判定原则：

- `conflict`：图片主体和文字商品目标都明确，且是互斥的商品目标。例如跑鞋图片配“推荐降噪耳机”。
- `consistent`：两者指向同类商品，或文字明确说明“找图中类似的跑鞋”。预算、品牌、颜色、场景、功效、肤质等筛选条件不是冲突。
- `uncertain`：图片不清、多主体、文字商品目标过宽泛、文字只是补充描述，或视觉模型不可用/超时。

`uncertain` 是内部状态，绝不能导致空回复、卡住或向用户暴露模型不确定性：有明确文字商品目标时继续完成文字优先的商品发现；文字目标不明确时继续原有图文检索，而不是由 Router 强制改写成纯图检索。

只有 `conflict` 才结束本轮并给出统一澄清：

> 图片看起来是{image_subject}，但你文字中想找的是{text_target}。请确认是按图片找相似{image_subject}，还是按文字找{text_target}？

视觉模型没有提供可靠主体/文字目标时，不判定为 `conflict`。

## 执行保护

仅靠 Prompt/Skill 不能保证每次 Tool Loop 都执行预检，因此增加窄执行保护：

1. `search_product_candidates` / 旧 `recommend_products` 只有在图文模式下才会暴露一致性检查 Tool，并在进入候选召回前完成一次预检。
2. 模型已经读取商品发现 Skill 但直接进入候选召回时，中间件自动补做这一次预检，而不是返回可纠正错误并消耗多轮模型重试。这样不改变能力选择，只把不可跳过的输入完整性检查稳定执行一次。
3. 已判定 `conflict` 时，候选召回工具被阻止，确保不会同时返回澄清和商品卡；观测中只记录预检，不把被拦截的召回标记为已执行。
4. 纯文本、纯图不暴露、不调用视觉一致性 Tool，也不增加视觉模型调用。

这不是关键词路由或品类枚举；代码只校验执行顺序和结果状态，语义判断仍由 qwen3.5-flash 完成。

## Router 收敛

删除 Router 对 `image_query_mode=image_only` 的“图片 + 模糊文字”强制纯图改写分支。

- 图片为空文字：仍是明确的纯图检索输入，保持 `input_mode=image`。
- 图片加文字：保持 Router 的语义结果并进入 ShoppingAgent；如为图文商品发现，由图文一致性 Skill 统一处理。

## 配置与降级

新增并同步到 `ai-service/.env.example` 和本地 `.env`：

```dotenv
SHOPPING_MULTIMODAL_CONSISTENCY_ENABLED=true
SHOPPING_MULTIMODAL_CONSISTENCY_MODEL=qwen3.5-flash
SHOPPING_MULTIMODAL_CONSISTENCY_TIMEOUT_SECONDS=6
```

视觉预检使用 DashScope 原生 `MultiModalConversation.call`：
`DASHSCOPE_MAAS_BASE_URL` 与 `qwen3.5-flash`。原生调用默认复用业务空间的
`LLM_API_KEY`；如需不同凭据可配置 `DASHSCOPE_NATIVE_API_KEY`。历史
`DASH_SCOPE_API_KEY` 保持给 embedding/rerank 通道使用，不能再覆盖原生视觉模型的
业务空间凭据。模型未配置、调用失败或超时时记录观测并返回 `uncertain`，继续原有链路，不能使用户请求失败。

图文冲突后，系统在会话业务记忆中短暂保存待确认的图片 URL、图片主体和文字目标。Router 只有在用户明确说“按图片/按图中这个找”时，才通过 `use_pending_image=true` 重新注入该图片；用户说“按文字找”或切换到可理解的新话题时立即清除，避免把旧图污染后续请求。

## 可观测性

每次触发预检的 Tool 结果与 trace 保留：`decision`、`image_subject`、`text_target`、`reason`、`model`、`fallback_used`、耗时。不得记录图片二进制或凭据。

## 验收与回归

定向测试覆盖：

1. 跑鞋图片 + “找类似跑鞋，预算 500 元以内” → `consistent`，只走一次候选召回。
2. 跑鞋图片 + “推荐降噪耳机” → `conflict`，返回澄清、零商品卡、零候选召回。
3. 图片不清/多主体 + 明确文字商品需求 → `uncertain`，继续产生正常推荐回复。
4. 图片 + “给我找这个东西” → Router 不再强制置为纯图模式；Shopping 链路正常结束，不空回复、不卡住。
5. 纯图片、纯文本、对比、详情 → 不调用视觉一致性 Tool。
6. 多轮：第一轮 `conflict` 后用户明确“按文字找耳机”或“按图片找跑鞋”，下一轮分别能完成对应检索，且不继承上一轮冲突状态。

人工冒烟时使用用户提供的可访问图片，并同时观察 SSE 完整性、`tool_calls`、商品卡和 LangSmith 中的视觉预检节点。

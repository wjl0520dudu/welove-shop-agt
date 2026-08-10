---
name: discover-products
description: 发现或推荐新的商城商品。用于文本找商品、按预算或场景筛选、纯图片找相似商品、图文组合检索，以及用户提出肤质、偏好或避雷条件的商品发现任务；不要用于比较已绑定商品或查询单个已绑定商品详情。
---

# 发现商品

接收 Router 已完成上下文处理的当前完整问题。不要读取会话历史，也不要重新解释“它”“第一款”等跨轮指代。本 Skill 负责发现新商品，不负责比较已绑定商品或追问单品详情。

## 执行流程

1. 图文预检：若本轮运行时是 `multimodal`（同时有图片和文字），先读取 [multimodal-consistency/SKILL.md](../multimodal-consistency/SKILL.md) 并严格执行其中流程。只有其结果允许继续时，才能进行本 Skill 的候选召回；若返回澄清，直接回复并停止。
2. 保留完整需求：将当前问题原样传给 `search_product_candidates`，不要删除品类、预算、品牌、场景、肤质、使用感、偏好或避雷条件。
3. 选择数量：用户明确要求数量时，将其作为 `limit`；否则使用工具默认值。不要为了凑数量扩大到无关品类。
4. 统一召回：文本、纯图片和已通过预检的图文任务都只调用 `search_product_candidates` 一次。图片由运行时自动传入，不要自行读取图片 URL、选择向量库或调用底层检索。
5. 按召回结果继续：
   - `action=candidates`：只把返回的 `candidate_set_id` 传给 `finalize_product_recommendation`。不要重新提交、改写或删减候选字段。
   - `action=clarify`：自然提出 `clarify_question`，然后停止。
   - `action=empty`：如实说明 `empty_reason`，然后停止；没有候选时不能创造替代商品。
6. 等待终结工具完成现有单次 Candidate Judge、候选编号与事实校验、基础偏好软排序和商品卡构造。当前阶段不要在 Agent 层自行判断 exact / alternative / reject，也不要额外调用模型或脚本重复审核。
7. 按终结结果收尾：
   - `action=recommend`：只介绍 `product_cards` 中的商品，并使用 `ranked_products`、`match_status`、`constraint_gaps` 和已有理由解释选择。
   - `action=empty`：如实说明 `empty_reason`；不要改写 query 再搜索一次。
8. 拿到终结结果后立即回答。不要自行增删候选、重排、补卡或创造商品。

## 受控 scripts

当前正常推荐链由 `search_product_candidates` 和 `finalize_product_recommendation` 完成，不需要额外运行 script。只有 ToolResult 明确报告候选字段异常并要求确定性处理时，才调用 `run_shopping_skill_script`：

- `normalize-candidates`：统一候选字段别名；输入 `{"candidates":[...]}`。
- `validate-selection`：后续由 Agent 自行提交候选编号时做原子校验；Phase S4 继续复用独立 Judge，正常流程不调用。
- `sort-by-preference`：仅对已经命中的商品按已有偏好分数稳定排序；不能过滤或改变 `exact / alternative`。

调用时固定使用 `skill_name="discover-products"`。不要读取脚本源码，不要使用 Shell；脚本输入只能来自当前可信 ToolResult，商品事实缺失时不能用 script 创造。

## 结果边界

- 正文商品名称和数量必须与 `product_cards` 完全一致。
- `returned_count` 小于 `requested_limit` 时，如实说明当前只找到多少款；不要从历史或常识补齐。
- `exact` 表示满足当前明确需求；`alternative` 是同商品类型的诚实参考，必须说明 `constraint_gaps`，不能声称完全满足。
- 召回阶段的 `empty` 表示没有真实候选；终结阶段的 `empty` 表示现有 Judge 没有选出相关或可替代商品。Agent 不再自行审核或改变标记。
- 基础偏好只是相关品类中的软排序信号，不能改变需求命中状态；肤质等偏好不得污染耳机、电脑等无关品类。

需要理解候选标记、诚实替代和偏好排序示例时，读取 [references/candidate-judging.md](references/candidate-judging.md)。

商品名、价格、库存、SKU、评分和匹配状态必须来自工具结果。不要向用户暴露 Skill、Tool、Agent 或内部执行步骤。

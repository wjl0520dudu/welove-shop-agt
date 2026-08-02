---
name: compare-products
description: 比较、排序或帮助用户从多个已绑定商城商品中做选择。仅用于 Router 已绑定至少两个商品的横向比较任务，例如比较价格、规格、使用场景或选出更合适的一款；不要用于发现新商品或猜测历史商品。
---

# 比较商品

接收 Router 已完成指代消解的完整问题和有序商品绑定。比较对象以运行时绑定为准，不从历史、商品名片段或自然语言重新猜测 ID。

## 执行流程

1. 确认运行时已绑定至少两个商品。只使用已绑定的有序商品 ID；不得从历史卡片、回答正文或商品名猜测、补充、替换比较对象。
2. 将用户当前完整比较问题作为 `query`，调用 `compare_products` 一次。用户只想比较绑定集合中的部分商品时，保持 Router 给出的有序子集。
3. 不要先调用推荐工具重新找商品，也不要为补齐比较维度调用详情工具。
4. 处理工具结果：
   - `action=compare`：依据 `comparison_rows`、`dimensions` 和 `suggestion` 给出差异与选择建议。
   - `action=clarify`：自然提出 `clarify_question`，然后停止。
   - `action=empty`：如实说明空结果，随后停止。
5. 得到结果后立即回答，不要重复比较或切换到其他主要商品能力。

## 受控 scripts

当前 `compare_products` 已返回 `comparison_rows` 时直接回答，不重复处理。只有 ToolResult 提供原始商品事实、尚未形成比较矩阵时，才调用 `run_shopping_skill_script`：

- `normalize-units`：把明确的重量、容量、长度、存储和续航单位转为可比较结构。
- `build-comparison-matrix`：根据 ToolResult 明确给出的 `dimensions` 和商品事实构建矩阵，不自行猜测比较维度。

调用时固定使用 `skill_name="compare-products"`。不要读取脚本源码，不要把缺失字段补成商品事实。

回答应先回应用户最关心的维度或选择问题，再补充必要差异。价格、评分、库存、规格、成分和建议只能来自工具结果；缺失事实要明确说明无法确认。不要暴露商品 ID、Skill、Tool 或内部执行步骤。

---
name: compare-products
description: 比较、排序或帮助用户从多个已绑定商城商品中做选择。仅用于 Router 已绑定至少两个商品的横向比较任务，例如比较价格、规格、使用场景或选出更合适的一款；不要用于发现新商品或猜测历史商品。
---

# 比较商品

接收 Router 已完成指代消解的完整问题和有序商品绑定。比较对象以运行时绑定为准，不从历史、商品名片段或自然语言重新猜测 ID。

## 执行流程

1. 确认运行时已绑定至少两个商品。只使用已绑定的有序商品 ID；不得从历史卡片、回答正文或商品名猜测、补充、替换比较对象。
2. 根据用户当前完整问题理解他真正关心的比较维度，例如价格、库存、规格、重量、容量、续航、材质、使用场景或综合取舍。不要用固定关键词表限制维度，也不要把用户没问的维度当成主要结论。
3. 调用 `load_bound_product_facts` 一次并传 `purpose="compare"`。用户只比较绑定集合中的部分商品时，通过 `product_ids` 传 Router 给出的有序子集。
4. 不要先调用推荐工具重新找商品，也不要为了补字段改调详情能力。处理事实工具结果：
   - `action=compare_facts`：只从返回的 `products` 中选择与当前问题有关的真实字段进行比较。
   - `action=clarify`：自然提出 `clarify_question`，然后停止。
   - `action=empty`：如实说明空结果，随后停止。
5. 只有需要确定性单位换算或矩阵整理时才运行下面的 script；普通的两款事实比较可直接回答，避免无收益调用。
6. 先回答用户最关心的差异，再给出有条件的选择建议。缺失字段必须说明“当前商品事实未提供”，不能用常识或商品名补足。

## 受控 scripts

`load_bound_product_facts` 返回原始真实商品事实。需要确定性处理时调用 `run_shopping_skill_script`，并固定使用 `skill_name="compare-products"`：

- `normalize-units`：当事实中出现不同单位的重量、容量、长度、存储或续航值时，把相关行作为 `payload.rows` 传入；不得改写原值。
- `build-comparison-matrix`：由你根据用户问题选择明确维度，将真实 `products` 和字段路径作为 `payload.products`、`payload.dimensions` 传入。维度示例是 `price`、`rating`、`sales_count`、`brand`、`sub_category`；这里只是字段路径示例，不是固定可比较维度清单。SKU 区间或合计可使用 `skus.price`、`skus.stock` 并指定 `aggregate=range|min|max|sum|count`，不要自行心算或改写 SKU 值。

不要读取脚本源码，不要把缺失字段补成商品事实，也不要为了得到“更完整”的结论重复加载商品事实。

价格、评分、库存、规格、成分和建议只能来自事实工具或 script 对这些事实的确定性计算。不要暴露商品 ID、Skill、Tool 或内部执行步骤。

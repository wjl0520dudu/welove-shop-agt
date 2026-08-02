---
name: inspect-product
description: 查询一个已绑定商城商品的价格、库存、SKU、规格、成分、在售状态、适配性或其他实时详情。仅用于 Router 已唯一绑定商品的单品追问；不要用于比较多件商品、发现新品或从历史猜测商品。
---

# 查询商品详情

接收 Router 已完成指代消解的完整问题和唯一商品绑定。不要重新解析“这款”“上一款”等表达，也不要自行选择其他商品。

## 执行流程

1. 确认运行时只绑定了当前要查询的商品。只使用该绑定 ID，不从历史卡片、焦点商品、商品名或代词猜测其他对象。
2. 根据用户当前完整问题理解他关心的事实，例如当前价格、SKU 价格区间、库存、颜色/容量/型号、商品描述、成分信息或是否适合某个场景。不要用固定关键词表把详情问法限制在预定义 focus 中。
3. 调用 `load_bound_product_facts` 一次并传 `purpose="detail"`；如运行时绑定集合不止一个，必须传唯一的 Router 绑定 `product_ids` 子集，不能自行挑选。
4. 处理工具结果：
   - `action=detail_facts`：只依据唯一 `products[0]` 中真实存在的字段回答当前问题。
   - `action=clarify`：自然提出 `clarify_question`，然后停止。
   - `action=empty`：如实说明当前无法确认的事实，随后停止。
5. 只有用户询问 SKU 价格区间、总库存或可售规格汇总时，才运行下面的 script；单一基础价格或普通描述可直接回答。
6. 得到事实后立即回答，不要再次加载详情，也不要追加推荐或比较。

## 受控 script

当 `products[0].skus` 存在且需要确定性汇总价格区间、总库存或可售规格时，调用 `run_shopping_skill_script` 的 `summarize-sku-facts`：固定使用 `skill_name="inspect-product"`，并把真实 `product` 或 `skus` 放入 payload。

不要读取脚本源码，不要使用 Shell。script 只能汇总输入中的真实 SKU，不能补充缺失规格或库存。

直接回答当前问题。未返回的价格、库存、SKU、功效、规格、成分或评价必须明确为当前无法确认，不能推测或用常识补足。不向用户暴露商品 ID、Skill、Tool 或内部执行步骤。

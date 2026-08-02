---
name: inspect-product
description: 查询一个已绑定商城商品的价格、库存、SKU、规格、成分、在售状态、适配性或其他实时详情。仅用于 Router 已唯一绑定商品的单品追问；不要用于比较多件商品、发现新品或从历史猜测商品。
---

# 查询商品详情

接收 Router 已完成指代消解的完整问题和唯一商品绑定。不要重新解析“这款”“上一款”等表达，也不要自行选择其他商品。

## 执行流程

1. 确认运行时只绑定了当前要查询的商品。只使用该绑定 ID，不从历史卡片、焦点商品、商品名或代词猜测其他对象。
2. 将用户当前完整详情问题作为 `query`，调用 `answer_product_detail` 一次，只查询用户关心的价格、库存、SKU、规格、成分、在售状态、适配性或概览。
3. 处理工具结果：
   - `action=detail`：只依据 `facts` 和 `product` 中真实存在的字段回答。
   - `action=clarify`：自然提出 `clarify_question`，然后停止。
   - `action=empty`：如实说明当前无法确认的事实，随后停止。
4. 得到结果后立即回答，不要再次查询详情，也不要追加推荐或比较。

## 受控 script

当前 `answer_product_detail` 已返回聚焦后的 `facts` 时直接回答。只有 ToolResult 提供原始 `product.skus`、且需要确定性汇总价格区间和库存时，才调用 `run_shopping_skill_script` 的 `summarize-sku-facts`，并固定使用 `skill_name="inspect-product"`。

不要读取脚本源码，不要使用 Shell。script 只能汇总输入中的真实 SKU，不能补充缺失规格或库存。

直接回答当前问题。未返回的价格、库存、SKU、功效、规格、成分或评价必须明确为当前无法确认，不能推测或用常识补足。不向用户暴露商品 ID、Skill、Tool 或内部执行步骤。

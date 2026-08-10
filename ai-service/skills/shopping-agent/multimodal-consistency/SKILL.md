---
name: multimodal-consistency
description: 图文商品发现前检查参考图片主体与用户文字商品目标是否明显冲突。仅用于同时带图片和文字的商品发现任务；不用于纯图片、纯文本、商品详情或商品对比。
---

# 图文商品目标一致性检查

本 Skill 只处理 Router 已交付的图文商品发现任务。不要读取会话历史，不要自行识别商品 ID，不要调用底层图片、向量库或检索接口。

## 执行流程

1. 调用 `check_multimodal_consistency`，把 Router 已消解的完整问题原样传入 `query`。不要删除预算、品牌、场景、肤质、功效或偏好条件。
2. 按 ToolResult 的 `action` 处理：
   - `action=clarify`：图片主体和文字商品目标已被可靠判定为冲突。直接、完整地向用户提出 `clarify_question`，然后停止；不得调用 `search_product_candidates`、`recommend_products` 或任何商品检索工具。
   - `action=consistency` 且 `decision=consistent`：继续已读取的 `discover-products` Skill。
   - `action=consistency` 且 `decision=uncertain`：继续已读取的 `discover-products` Skill。文字商品目标明确时，运行时会文字优先检索；文字目标仍模糊时保留图片参与检索。`uncertain` 只是内部视觉不确定状态，绝不能回复为空、卡住或向用户说“模型不确定”。
3. 不要根据图片或文字自行修改 `decision`；预算、颜色、品牌、场景、肤质、功效、偏好等条件不是图文冲突。

## 结果边界

- 只有 ToolResult 明确为 `action=clarify` 才能终止本轮商品发现。
- 正常继续时，后续商品事实、候选、筛选、Judge、软排序和商品卡仍完全由 `discover-products` Skill 及其高层工具负责。
- 不暴露 Skill、Tool、视觉模型或内部判定字段。

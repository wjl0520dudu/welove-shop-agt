# WeLove Shop Agent Golden Dataset

`agent_golden_cases.jsonl` 是当前 Agent 的固定离线基线，共 142 条 Case。它既供本地 `run_agent_eval` 执行，也将作为下一阶段同步至 LangSmith Dataset 的唯一来源；不要在 LangSmith 页面直接修改样本，避免本地与云端版本漂移。

## 场景覆盖

| 场景 | 数量 | 覆盖内容 |
| --- | ---: | --- |
| `shopping` | 46 | 推荐、详情、比较、预算/偏好、商品指代与空结果 |
| `knowledge` | 32 | 常规知识、风险知识、证据问答与知识指代 |
| `chitchat` | 32 | 日常聊天、会话回顾、模糊/越界输入 |
| `multimodal_shopping` | 20 | 纯图、图文、预算、图片质量与无关图片 |
| `multi_agent` | 12 | 复杂问题、并行/依赖子任务、部分失败隔离 |

数据集契约由 `evals.dataset_contract` 校验；`agent_golden_cases.manifest.json` 是数量与分层基线。若要增删 Case，必须同时有意更新 manifest、契约测试和实验报告基线，不能静默改变数量。

## 单条 Case 格式

```json
{
  "id": "shop-024",
  "scenario": "shopping",
  "tags": ["multi_turn", "reference", "ordinal"],
  "setup": [{"input": "推荐几款适合油皮的防晒霜"}],
  "input": "第一个多少钱",
  "request": {"image_url": "https://..."},
  "expected": {
    "routes": ["shopping"],
    "task_types": ["shopping"],
    "required_tools": ["answer_product_detail"],
    "require_product_cards": false,
    "product_categories": ["防晒"],
    "retrieval_grades": {"10": 2},
    "reference_answer": "根据上一轮推荐的第一款商品报价。",
    "max_latency_ms": 15000,
    "require_sse": true
  }
}
```

字段说明：

- `setup`：多轮前置消息。评测器会为 setup 和主问题复用同一个随机 `conversation_id`，因此测试的是真实会话承接，而不是手工拼接历史。
- `request`：只放 API 请求参数，例如 `image_url`、`user_id`、`skin_type`、`preference_tags`；不可包含密钥或真实用户隐私。
- `routes`、`task_types`：允许值列表，用于兼容安全降级路线；其中至少要有一个期望值。
- `required_tools`、商品卡、品类、SSE：程序化硬契约。无此要求时可省略，避免把不稳定的实现细节误判为失败。
- `reference_answer`：供下一阶段 LLM-as-a-Judge 使用的语义锚点，不等于要求模型逐字复述。
- `retrieval_grades`：仅为有人工/业务相关性标注的 Case 提供，用于 Recall@K、MRR@K、NDCG@K。

## 本地验证

从 `ai-service` 目录执行：

```powershell
python -m pytest -q tests/test_agent_evaluation.py
```

该命令不会调用模型、Milvus 或 LangSmith。在线执行和导入 LangSmith 留给 P2；执行前须先确保图片 URL 可访问。

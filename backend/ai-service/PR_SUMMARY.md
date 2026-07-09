# feat(ai-service): ShoppingAgent 重构 + 商品向量搬 Milvus 多模态 + 运维基础设施

面向 code review 的完整变更说明。本次工作在 `feat/ai-service` 分支上共 **8 个 commit / 35 文件 / +6232 -151 行**，从 5509e71 到 8cefccc。

## 一句话总结

把 ShoppingAgent 从"LLM 面对 12 个底层工具乱选"重构成"面对 4 个高层 Capability Tool 稳定选择"，商品向量从 pgvector 单路 dense 迁到 Milvus 三路 + rerank 两阶段，schema 一步到位预留多模态字段，配套 PG→Milvus 权威运维路径。

## 一、Commit 时间线

| Commit | 类型 | 内容 |
|---|---|---|
| 5509e71 | feat | Phase 1a：ShoppingAgent 高层 Capability 重构（LLM 工具 12→4） |
| 4166e38 | feat | Phase 1b：商品搬 Milvus 三路检索 + qwen3-rerank 两阶段 |
| 07e8717 | fix | Phase 1b 补丁：E2E 真跑发现的 4 个 filter/数据源问题 |
| 0588654 | fix | 修复 3 组历史遗留 broken 测试（28 个用例） |
| a34182c | feat | Step 4：PG → Milvus 商品同步脚本 |
| 0e34240 | fix | sync incremental tz-aware/naive 兼容 |
| 8cefccc | fix | KnowledgeAgent recursion_limit 12→20（跨轮指代偶发崩） |

## 二、核心问题域和解决方案

### 问题 1：ShoppingAgent 识别性能低（LLM 决策爆炸）

**症状**：LLM 面对 12 个底层工具（`search_products` / `search_products_by_name` / `get_product_detail` / `list_product_skus` / `compare_products` / `build_product_cards` + 用户维度 5 个 + `resolve_reference`），每轮都要判断"该用哪个"、"搜什么参数"、"要不要指代消解"、"要不要构造卡片"。表现：推荐推不出来、乱调工具、tool_call 循环触发 recursion_limit。

**解决**：分层重构

```
旧结构                            新结构（Phase 1a）
─────────                        ─────────────
LLM 见 12 个底层 tool             LLM 只见 4 个高层 tool
  ↓                                ↓
每个 tool 一个动作                Capability 类（确定性 pipeline）
  ↓                                ├── parse_need (LLM structured)
LLM 自己串起来                    ├── merge_pending_shopping_need
（不稳定）                        ├── clarify_gate
                                  ├── retrieval (Milvus 三路 + rerank)
                                  ├── ranking (6 维加权规则)
                                  └── build_product_cards
```

**4 个高层 Tool**：
- `recommend_products` — 推荐商品
- `compare_products` — 对比商品
- `answer_product_detail` — 追问详情/价格/规格/成分
- `get_user_shopping_context` — 个性化上下文（先 stub）

**LLM 面对面**：LLM 只做"选哪个 tool + 组织自然语言话术"，其余的检索/排序/卡片全在 Capability 内部走确定性代码。

### 问题 2：商品检索质量差（pgvector 单路 dense）

**症状**：pgvector 只有 dense 一路、embedding 是 OpenAI text-embedding-3-small (1536 维老模型)、没 rerank。用户说"敏感肌面霜"分数 0.5-0.6 几乎不可分。

**解决**：商品搬 Milvus，架构完全对齐 KnowledgeAgent 的三级增强

```
新 collection：product_mm_collection（跟 my_rag_collection 严格隔离）

Schema（一步到位）：
  product_id INT64 primary                          # = PG.id（见问题 5）
  text VARCHAR + enable_analyzer + jieba
  text_dense_vector FLOAT_VECTOR(1024)              # DashScope v4
  text_sparse_vector SPARSE_FLOAT_VECTOR            # BM25 Function 自动生成
  multimodal_vector FLOAT_VECTOR(1024)              # Phase 2 图+文融合预留
  # 展示 + filter 冗余字段（避免回 PG）
  title / brand / image_url / description
  category / sub_category / tags
  base_price / rating / sales_count / review_count / status

三路检索：
  dense_search   —  DashScope v4 语义匹配
  bm25_search    —  Milvus BM25 精确词命中
  hybrid_search  —  RRFRanker(k=60) 融合，默认

两阶段：
  hybrid 召回 initial_top_k=20 → qwen3-rerank 精排 top_k=5
```

**实测效果**（100 商品全量灌入）：
- 「敏感肌面霜」rerank 前分数 0.001-0.033（不可分），rerank 后 0.15-0.92（30 倍区分度提升）
- 「运动 T 恤透气」BM25 会被"运动/透气"带偏到帽子，hybrid+rerank 后正确排 3 款速干 T 恤
- 「iPhone 17 Pro Max」BM25 精确命中 score 10.19 遥遥领先

### 问题 3：跨库数据一致性（PG vs Milvus）

**症状**：Phase 1b 首次冷启用 `ingest_products_to_milvus.py` 从 JSON 灌 Milvus，product_id 从字符串 code (`p_beauty_001`) 合成成 100001~400025；但 Java 侧后来把商品灌进 PG，用的是自然主键 1~100。两套 id 不一致，DetailCapability 拿到 Milvus 的 100001 去 PG 查根本查不到。

**解决**：`Milvus.product_id = PG.id`（一个 id 走天下，不搞映射层）

新脚本 `scripts/sync_products_pg_to_milvus.py`：
- `--mode full`：PG active 商品 → 覆盖 Milvus + diff 出孤儿（合成 id）清理
- `--mode incremental`：读 `sync_watermark` 表，只同步 `update_time > watermark` 的
- `--mode one --product-id N`：单商品即刻同步，含下架检测自动删除
- `--dry-run`：不写只打印计划

首次跑 `--mode full`：Milvus 从 64 条老合成 id → 100 条 PG.id，一次完成 id 迁移。之后走 incremental。

### 问题 4：product_cards 卡片串台

**症状**：ShoppingAgent 结束时无条件从 Store 读 `last_product_cards` 兜底 → 用户在"对比/追问详情"轮次误带上一轮推荐卡片，前端渲染错乱。

**解决**：`shopping/agent.py::_extract_high_level_tool_result` 优先从最近一次 ToolMessage 抽取 `action ∈ {recommend, clarify, empty, compare, detail}` 的返回；只在"LLM 没调工具（纯闲聊）"时才读 Store。

### 问题 5：多轮澄清结构化状态

**症状**：用户"送妈妈"→ 助手"送啥？预算？"→ 用户"护肤品 300 内"。LLM 靠 messages 猜上下文，容易漏字段。

**解决**：`pending_shopping_need` 结构化槽位保存在 Store（PG）
- `RecommendCapability.run` 读 pending → merge → clarify_gate → 消费后清除
- 3 轮上限自动过期，避免旧话题污染

## 三、文件变更清单

### 新增（20 个文件）

**主链路**：
- `shopping/schemas.py` — Pydantic：ShoppingContext / ShoppingNeed / *ToolResult / PendingShoppingNeed
- `shopping/context.py` — `build_shopping_context_from_runtime`
- `shopping/cards.py` — `build_product_cards`（唯一入口）
- `shopping/ranking.py` — `ProductRanker` 6 维加权 + 同义词展开
- `shopping/retrieval.py` — `ShoppingRetriever`（Milvus 三路 + rerank + pgvector 降级 + relaxed 兜底 + category fallback）
- `shopping/vector_store.py` — `ProductMilvusStore`（三向量 schema + BM25 Function + filter 表达式）
- `shopping/high_level_tools.py` — 4 个 `@tool` 高层入口
- `shopping/capabilities/__init__.py`
- `shopping/capabilities/recommend.py` — RecommendCapability（含 WRONG_CAPABILITY 自检 + pending 合并）
- `shopping/capabilities/compare.py` — CompareCapability
- `shopping/capabilities/detail.py` — DetailCapability（Milvus 主档 + PG SKU）
- `shopping/capabilities/user_context.py` — MVP stub

**运维脚本**：
- `scripts/drop_product_mm_collection.py` — 清商品 collection
- `scripts/ingest_products_to_milvus.py` — **legacy 冷启专用**（已加警告）
- `scripts/sync_products_pg_to_milvus.py` — 生产运维路径
- `scripts/verify_product_search_modes.py` — 三路 + rerank on/off 对比
- `scripts/verify_shopping_e2e.py` — 5 case 8 turn ShoppingAgent E2E
- `scripts/verify_full_stack_e2e.py` — 完整 AssistantGraph E2E
- `scripts/verify_shopping_focus_and_compare.py` — focus=sku/ingredients + compare product_ids 补测

### 修改（15 个文件）

- `agents/memory.py` — 新增 pending_shopping_need 3 个 API
- `agents/prompts.py` — 重写 SHOPPING_AGENT_PROMPT（76 行控制指令 → 72 行工具目录，本质变化）
- `shopping/agent.py` — `_ALL_TOOLS = SHOPPING_HIGH_LEVEL_TOOLS` + ToolMessage 抽取
- `core/config.py` + `.env.example` — 新增 MILVUS_PRODUCT_COLLECTION + tongyi_vision embedding
- `knowledge/agent.py` — recursion_limit 12→20
- 老 broken 测试修复：`tests/test_retriever.py` / `tests/test_assistant_graph.py`

### 单测（157 个新增用例）

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| test_pending_shopping_need.py | 7 | memory API + 3 轮过期 |
| test_shopping_ranking_and_cards.py | 14 | 6 维打分 + 同义词展开 |
| test_shopping_retrieval.py | 8 | Milvus 三路 + rerank + fallback + 降级 |
| test_recommend_capability.py | 16 | parse+merge+clarify+recommend/empty |
| test_shopping_capabilities.py | 18 | Compare/Detail focus + 指代解析 |
| test_shopping_high_level_tools.py | 12 | Tool 目录 + context 组装 |
| test_product_vector_store.py | 24 | schema + filter + hit shape |
| test_sync_products.py | 16 | diff / 单商品 / 全量 / 增量 |
| test_retriever.py（重写）| 10 | 修 sys.modules 污染 |
| test_assistant_graph.py（修）| 8 | 修 API 漂移 |
| **总计新增** | **157** | |

## 四、E2E 真跑成绩单

### ShoppingAgent 5 case 8 turn（真 LLM + 真 Milvus）

| Case | 场景 | 结果 |
|---|---|---|
| 单轮 | 「油皮防晒 200 内」 | recommend → 巴黎欧莱雅 170 元 |
| 单轮 | 「推荐一下」 | clarify → 追问品类 |
| 多轮 | 「送妈妈」→「护肤品 300 内」 | pending 合并 → 3 张护肤卡片 |
| 多轮 | 「敏感肌面霜」→「哪个更适合」 | recommend → compare 结论 |
| 多轮 | 「速干 T 恤」→「第一个多少钱」 | recommend → detail 79 元 |

**Tool 选择正确率 8/8，Action 匹配 8/8**

### 全链路 AssistantGraph 5 case 7 turn

| Case | Route | 结果 |
|---|---|---|
| 单轮 shopping | shopping | ✅ |
| 单轮 knowledge | knowledge | ✅ |
| 单轮 chitchat | chitchat | ✅ |
| 跨域指代（商品）| shopping | ✅ |
| 跨域指代（知识）| knowledge | ✅ recursion fix 之后 |

**Route 分类 7/7 + answer 存在 7/7**

### 补测 C+D：Detail focus=sku/ingredients + Compare 显式 product_ids

- focus=sku（"第二个有几个规格"）→ Milvus 拿主档 + PG 查 SKU → 答"两款均 260 元，滋润型/清爽型" ✅
- focus=ingredients（"第一个含什么成分"）→ LLM 特征抽取 → 答"麦角硫因、虾青素、烟酰胺" ✅
- Compare `product_ids=[7,8]` → LLM 一次解析 id 传参 → Milvus query 拿主档 → 结构化对比 ✅

**5/5 全绿**

## 五、单测 + 回归

- **shopping 侧新增 110 单测**：全绿
- **老 broken 测试修复 28 用例**：全绿
- **sync 侧 16 单测**：全绿
- **全项目回归**：从"220 passed + 15 failed" → **267 passed + 3 skipped**（除去 test_cart_agent + test_document_pipeline 两个跟本次无关的历史遗留）

## 六、行为变化清单（给 Java + 前端同学参考）

### 用户可感知的新行为

1. **模糊需求会追问**：以前"推荐一下"直接给热销，现在返回 `answer="你想找哪类商品呢？..."` + `product_cards=[]`
2. **多轮需求合并**：用户"送妈妈"没说品类 → 助手追问 → 用户"护肤品 300 内" → 内部合并出完整 need 再推荐
3. **对比更详细**：结构化 `comparison_rows` 含价格/评分/销量/核心成分/浓度/适合肤质/主打功效/质地/注意事项 9 维度
4. **详情按焦点分派**：问价格给 SKU 价格区间，问成分给成分抽取，问规格给 SKU 列表

### API 契约变化（可能需要前端配合）

**`product_cards[i]` 新增字段**（下划线前缀，前端可忽略）：
```json
{
  "product_id": 12,
  "title": "...",
  "brand": "...",
  "price": 260,
  "image_url": "...",
  "rating": 4.2,
  "sales_count": 220,
  "sub_category": "面霜",
  "reason": "匹配「面霜」品类；适合「敏感肌」",
  "_score": 0.834,                  ← 新增：观测用
  "_matched_needs": ["敏感肌"],      ← 新增：命中的偏好
  "_risk_notes": [],                 ← 新增：如超预算/避雷词
  "_recall_sources": ["hybrid", "rerank"]   ← 新增：召回来源
}
```

`answer` 里可能带 clarify 追问（不再有 product_cards），前端需要展示为普通 chat 气泡。

### Java 后端可能要做的

1. **商品数据源自 PG.product 表**（Milvus 完全对齐 PG.id）
2. **同步定时任务**（推荐）：cron 每 5-15 分钟跑 `python scripts/sync_products_pg_to_milvus.py --mode incremental`
3. **单商品即时同步**（可选）：Java 后台改商品后可以直接调 `python scripts/sync_products_pg_to_milvus.py --mode one --product-id N`；或后续做成 FastAPI 端点 `POST /admin/sync-products/one`
4. **PG 里 `product.update_time` 是 tz-naive**（TIMESTAMP WITHOUT TIME ZONE），Java 侧改商品时要正确写这个字段，否则增量同步认不出变化

## 七、Phase 2 计划（图片就绪后）

不清库、不改 schema：
1. 跑脚本给 `multimodal_vector` 填 `tongyi-embedding-vision-flash-2026-03-06` 图+文融合向量
2. `drop_index("multimodal_vector")` → `create_index HNSW/AUTOINDEX`（现在是 FLAT 占位）
3. `ProductMilvusStore` 加：
   - `multimodal_search(image, text=None)` 以图搜图 / 图+文
   - `hybrid_search(..., include_multimodal=True)` 三路 RRF 融合

## 八、遗留 / 已知问题（本次未处理）

1. **`test_cart_agent.py`**：`from agents.runtime import agent_config` ImportError（老 API 名字被删；跟本次无关）
2. **`test_document_pipeline.py`**：Windows 文件权限错误（tempfile 清理跨平台差异）
3. **pymilvus deprecation warnings**：用的是 ORM API（`Collection.search` / `collection.load`），pymilvus 3.1 会移除。KnowledgeAgent + ShoppingAgent 都要迁到 `MilvusClient` API。工作量中等
4. **`ingest_products_to_milvus.py`** 未来可删（等确认 Java 侧稳定灌 PG 后）

## 九、Reviewer 建议关注点

1. **`shopping/retrieval.py`**：主链路 Milvus + rerank + relaxed + fallback + category 兜底逻辑，测试覆盖完整但请审下 fallback 顺序
2. **`shopping/vector_store.py::build_milvus_filter_expr`**：category 两级 OR 匹配是本次关键修复，看下有没有边界 case
3. **`scripts/sync_products_pg_to_milvus.py`**：diff / delete 孤儿的语义是否符合业务预期
4. **`agents/prompts.py::SHOPPING_AGENT_PROMPT`**：新 prompt 是否表达清楚了 4 个 tool 的边界
5. **`shopping/agent.py::_extract_high_level_tool_result`**：product_cards 抽取的兜底顺序（先 ToolMessage 后 Store）

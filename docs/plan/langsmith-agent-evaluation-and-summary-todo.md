# LangSmith 评测与滚动摘要待办清单

> 当前基线：`54f9693 feat(context): 实现统一滚动摘要与共享会话上下文`

## P0：统一滚动摘要

- [x] 原始消息由 `chat_svc.message` 完整保存，摘要在 `conversation_context` 单行持久化。
- [x] `resolve_context` 统一提供“持久化摘要 + 最近原文”，Router 与 ChitchatAgent 共用。
- [x] 摘要异步生成，不阻塞用户 SSE。
- [ ] 使用登录态 H5 完成一次跨阈值多轮验收，并确认数据库摘要落库与历史回顾效果。

## P1：142 条标准评测集

- [x] 固化 142 条 JSONL Golden Case，覆盖 Shopping、Knowledge、Chitchat、图文检索与复杂 DAG。
- [x] 支持 `setup` 多轮前置会话、图片请求、SSE、工具、商品卡、品类、检索等级与答案锚点。
- [x] 新增数据集 manifest、结构校验和定向测试，阻止 Case 数量/分层被静默改变。
- [x] 规定本地 JSONL 是唯一编辑源，P2 中同步到 LangSmith 而非在云端直接改数据。

## P2：LangSmith Dataset 与实验运行

- [x] 编写 JSONL → LangSmith Dataset 同步命令，支持 dry-run、数据集版本/指纹和稳定 Example ID 幂等更新。
- [x] 为每次评测运行写入实验元数据：Git commit、Shopping/Knowledge runtime、滚动摘要开关、模型、Prompt 指纹和检索配置。
- [x] 将本地评测的每条 Case 关联到 LangSmith trace；根 Trace 与子节点可按 evaluation_run_id、case_id、variant 过滤。
- [x] 新增 P2 操作指南，覆盖 Dataset 首次同步、小型实验运行和 Trace 查询。
- [x] 启动 ai-service 后运行 HTTP Case，确认远端 Trace 可按 `evaluation_run_id` 与 `evaluation_case_id` 查询；Knowledge Case 的业务失败仅因本次 Milvus 未连接。

## P3：评测器与指标

- [x] 程序化断言：路由准确率、工具选择、复杂任务覆盖、商品卡相关/无关率和 SSE 完整性，复用 Golden Contract 并作为 LangSmith Feedback 写回。
- [x] 低频 LLM-as-a-Judge：通过 `--deepeval` 显式启用；默认不调用，且不进入线上主链。
- [x] 从本地实测与 LangSmith Experiment Feedback 汇总 TTFT、P50/P95、真实 LLM Leaf Token 与失败归因；`--include-stream` 验证 `start → token → final → done`。
- [x] 输出版本可比较的 JSON/Markdown 报告与失败样本列表，`--baseline` 生成版本增量。
- [x] 真实环境完成流式/Token 冒烟与 142 条全量 Experiment 基线。

## P4：对比实验与报告

- [ ] 在历史 commit/独立 worktree 运行 Legacy baseline；不把旧 Agent 重新接回当前生产主链。
- [ ] 对比 Legacy、Skills、滚动摘要、Skills + 滚动摘要四个变量组合。
- [ ] 142 条全量运行后发布报告：指标变化、成本/延迟和失败样本归因。

## P5：数据驱动优化

- [ ] 根据实验中真实失败类型决定 Skills、Prompt、检索、RAG 分块或 DAG 的优化优先级。
- [ ] Sandbox 与 Skills 性能优化保持后置；当前 Agent 不执行 Shell/文件写操作，无需为了形式引入 Sandbox。

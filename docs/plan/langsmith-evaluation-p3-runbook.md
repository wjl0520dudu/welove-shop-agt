# P3：LangSmith Experiment 与自动评分操作指南

## 目标

本阶段把已同步的 142 条 Golden Dataset 和已有的真实 Agent Trace 收敛为一次正式、可比较的 LangSmith Experiment。

执行一次命令会完成以下事情：

1. 从 LangSmith Dataset 读取所选 Golden Case；本地 JSONL 仍是唯一可编辑源。
2. 对每个 Case 调用真实的 ai-service HTTP 接口；多轮 `setup` 与主问题共用一个新的会话 ID。
3. 创建 LangSmith Experiment，并对每个 Experiment Run 写入代码化 Feedback。
4. 向真实 ai-service 请求传入 `evaluation_run_id`、`case_id`、`variant` 等 Header，使 AssistantGraph Trace 可与 Experiment 对照。
5. 在 `ai-service/evals/reports/` 输出相同批次的 JSON 和 Markdown 本地报告。

P3 不改动线上用户请求路径；LLM Judge 只在命令显式传入 `--deepeval` 时运行。

`--include-stream` 会为每条选中 Case 额外执行一次隔离的 SSE 回放，验证 `start → token → final → done`，并记录 TTFT。Token 成本只汇总正常 `run` 请求的 LLM Leaf Trace，不把 SSE 回放的重复成本混入版本成本指标。

## 已上报指标

| 指标 | 方式 | 适用条件 |
|---|---|---|
| `contract_pass` | 现有 Golden Contract | 所有 Case |
| `route_accuracy` / `task_type_accuracy` | 预期路由与实际返回比对 | Case 声明相应预期 |
| `tool_selection_correctness` | 预期工具与真实工具调用比对 | Case 声明 `required_tools` |
| `product_card_validity` | 商品卡 ID、重复性等 | Case 要求商品卡 |
| `product_card_relevance` | 标注品类是否命中 | Case 标注品类 |
| `product_card_relevance_rate` / `irrelevant_product_card_rate` | 卡片级相关/无关比例 | 有商品卡和品类标注 |
| `complex_subtask_coverage` / `complex_task_completion` | DAG 子任务路由与完成状态 | 复杂任务 Case |
| `sse_integrity` | 是否产生 `start → token → final → done` | SSE Case 或 `--include-stream` |
| `latency_ms` / `ttft_ms` | HTTP 实测原始毫秒值 | 延迟始终；SSE Case 或 `--include-stream` |
| `input_tokens` / `output_tokens` / `total_tokens` | 同 Case 真实 AssistantGraph LLM Leaf Trace 汇总 | ai-service 已上报 LangSmith Trace |
| `llm_task_completion` / `llm_tool_correctness` | DeepEval LLM-as-a-Judge | 显式加 `--deepeval` |

“约束满足率”只对数据集显式标注的硬约束计算。当前 v1 Case 的正式可判定标注以路由、工具、商品品类、卡片、子任务和 SSE 为主；不要把未标注的预算、肤质等自然语言条件伪装成确定性分数。后续补充人工约束标签后，可在同一 Contract 中增加该指标。

## 前置条件

- 已在 `ai-service/.env` 配置并启用：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=welove-shop-ai
LANGSMITH_EVAL_DATASET=welove-shop-agent-golden-v1
```

- ai-service 已启动，且 `http://127.0.0.1:8000/health/live` 返回 200。
- 需要的 DashScope、Milvus、PostgreSQL 等依赖已按要测的场景启动。
- Dataset 已同步完成。只有变更本地 JSONL 后才需重新同步：

```powershell
cd D:\dev\project\py\welove-shop-agt\ai-service
D:\dev\env\conda_envs\wlagt\python.exe -m evals.sync_langsmith_dataset --apply
```

## 推荐执行顺序

如需先确认远端 Dataset 中确实有选中的 Case、但不创建 Experiment 也不调用 ai-service：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_langsmith_experiment --limit 3 --dry-run
```

先跑 3 条冒烟，确认 Experiment、Feedback 和 Trace 都能看到：

```powershell
cd D:\dev\project\py\welove-shop-agt\ai-service
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_langsmith_experiment `
  --limit 3 `
  --variant skills-summary-on `
  --experiment-prefix skills-summary-on-smoke `
  --evaluation-run-id skills-summary-on-smoke-001 `
  --timeout-seconds 45 `
  --max-concurrency 1 `
  --include-stream
```

确认无误后运行全量 142 条。默认单并发，避免本地 Milvus、模型和 ai-service 被压垮；确认稳定后再将并发提高到 2。

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_langsmith_experiment `
  --variant skills-summary-on `
  --experiment-prefix skills-summary-on-v1 `
  --evaluation-run-id skills-summary-on-v1-001 `
  --timeout-seconds 60 `
  --max-concurrency 1
```

只测某类场景或单个问题：

```powershell
# 只测知识问答
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_langsmith_experiment --scenario knowledge --limit 5

# 精确复现一个失败 Case
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_langsmith_experiment --case-id shop-001
```

LLM-as-a-Judge 会额外消耗模型调用，先用小样本验证。它不参与线上 Agent：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_langsmith_experiment `
  --scenario knowledge `
  --limit 5 `
  --deepeval `
  --judge-threshold 0.6
```

## 查看结果与对比

命令结束后会输出两个本地文件，例如：

```text
ai-service/evals/reports/skills-summary-on-v1.json
ai-service/evals/reports/skills-summary-on-v1.md
```

LangSmith 中打开 `LANGSMITH_PROJECT` 项目：

- Experiments 页面查看 `--experiment-prefix` 对应实验及上述 Feedback 指标；
- 点击某个失败 Run 查看其输入、输出和 `contract_pass` 失败原因；
- 以 `evaluation_run_id=skills-summary-on-v1-001` 过滤 Trace，可查看同一 Case 的真实 AssistantGraph Router、Skill、Tool、DAG 子节点；
- 本地报告中的 `langsmith_trace.trace_id` 可与请求日志交叉定位。

对比两个版本时，将前一个 JSON 报告传入 `--baseline`：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_langsmith_experiment `
  --variant candidate-version `
  --baseline evals/reports/skills-summary-on-v1.json
```

报告会给出 Contract/Task Success/Pass@1、P95 Latency、P95 TTFT 的增减以及新增失败 Case。P4 再使用独立 worktree 跑 Legacy、Skills、摘要开关的四个版本组合，避免把旧实现重新接回当前线上主链。

## 边界

- `LANGSMITH_HIDE_INPUTS/OUTPUTS=true` 时，线上 Agent Trace 按现有隐私策略隐藏正文；Experiment Feedback 和本地报告仍可用。
- Token 来自 `run_type=llm` 的真实模型 Leaf Run，仅计算 `evaluation_operation=run`；如果 Trace 因网络延迟尚未上传，报告会保留缺失样本数而非填充为 0。
- P3 的性能数据是本机、当前依赖状态下的实测值，不能直接作为生产 SLA。
- 若 Milvus、DashScope 等依赖异常，Case 会显示真实 `EVAL_HTTP_ERROR` 或业务错误；这不是评测器自动放宽的通过结果。

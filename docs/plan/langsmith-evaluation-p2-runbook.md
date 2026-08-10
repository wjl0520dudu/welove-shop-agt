# P2：LangSmith Dataset 同步与实验 Trace 操作指南

> 适合本地执行。数据集来源固定为 `ai-service/evals/datasets/agent_golden_cases.jsonl`，共 142 条；不要在 LangSmith 网页直接修改样本。

## 1. 配置

确认 `ai-service/.env` 已有以下配置。API Key 只保存在本地 `.env`，不得提交：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=你的Key
LANGSMITH_PROJECT=welove-shop-ai-dev
LANGSMITH_ENVIRONMENT=development
LANGSMITH_EVAL_DATASET=welove-shop-agent-golden-v1
```

重启 ai-service，使服务进程读取最新 `.env`。普通 H5 请求不会携带评测标记，不会被归入实验。

## 2. 首次同步 Dataset

在 `ai-service` 目录，使用项目虚拟环境：

```powershell
# 先检查会上传什么；默认不会写 LangSmith。
D:\dev\env\conda_envs\wlagt\python.exe -m evals.sync_langsmith_dataset

# 确认显示 example_count=142 后，才创建/更新远端 Dataset。
D:\dev\env\conda_envs\wlagt\python.exe -m evals.sync_langsmith_dataset --apply
```

同步使用 `dataset 名称 + 数据集版本 + case_id` 生成稳定 UUID。因此重复执行 `--apply` 是幂等 upsert，不会重复累加 142 条样本。

## 3. 运行一个小型实验

启动 ai-service、LLM 和所需的检索依赖后，先跑 5 条：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_agent_eval `
  --base-url http://127.0.0.1:8000/api/assistant `
  --limit 5 `
  --timeout-seconds 45 `
  --experiment-name skills-summary-on `
  --evaluation-run-id skills-summary-on-smoke-001 `
  --output evals/reports/skills-summary-on-smoke-001.json `
  --markdown-output evals/reports/skills-summary-on-smoke-001.md
```

`--evaluation-run-id` 是一次实验批次的稳定标识，后续重跑同一批次时应改成新值；`--experiment-name` 是用于报告和版本对比的人类可读名称。

## 4. 在 LangSmith 找到对应 Trace

每条在线评测请求会附带：

```text
evaluation_run_id
evaluation_case_id
evaluation_dataset
evaluation_variant
```

它们会出现在根节点 `assistant.request` 及所有子节点的 metadata。打开 `.env` 中 `LANGSMITH_PROJECT` 对应项目，以 `evaluation_run_id=skills-summary-on-smoke-001` 过滤，再以 `evaluation_case_id` 定位某条失败 Case。评测报告的每条结果也保留相同 `langsmith_trace.trace_id`，可以与 API 日志的 `X-Trace-Id` 对照。

## 5. 目前边界

- P2 只完成 Dataset 同步、实验身份和 Trace 关联；尚未在 LangSmith 中自动生成评分/比较实验。
- 代码 Contract、LLM-as-a-Judge、RAGAS、P50/P95/TTFT 汇总和四版本实验报告属于 P3/P4。
- 如果 `LANGSMITH_TRACING=false`，本地报告仍会生成，但 LangSmith 页面不会出现 Trace。

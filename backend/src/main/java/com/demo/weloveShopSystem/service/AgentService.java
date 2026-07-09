package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.dto.AgentRunRequest;
import com.demo.weloveShopSystem.dto.AgentRunResponse;

/**
 * Agent 编排服务接口。
 */
public interface AgentService {
    /** 运行一次 Agent 任务。 */
    AgentRunResponse runAgent(AgentRunRequest request);

    /** 取消正在运行的 Agent 任务。 */
    boolean cancelAgentRun(String runId);

    /** 根据历史运行 ID 重试 Agent 任务。 */
    AgentRunResponse retryAgentRun(String runId);
}

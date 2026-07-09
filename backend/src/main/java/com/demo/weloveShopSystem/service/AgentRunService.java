package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.dto.AgentRunResponse;
import com.demo.weloveShopSystem.entity.AgentRun;

import java.util.List;

/**
 * Agent 运行记录服务接口。
 */
public interface AgentRunService {
    /** 保存 Agent 运行记录。 */
    void saveAgentRun(AgentRun agentRun);
    /** 更新 Agent 运行记录。 */
    void updateAgentRun(AgentRun agentRun);
    /** 根据数据库 ID 查询运行记录。 */
    AgentRun getAgentRunById(String id);
    /** 根据业务 runId 查询运行记录。 */
    AgentRun getAgentRunByRunId(String runId);
    /** 根据数据库 ID 查询运行响应详情。 */
    AgentRunResponse getAgentRunResponseById(String id);
    /** 查询指定会话下的 Agent 运行记录。 */
    List<AgentRun> getAgentRunsByConversationId(String conversationId);
    /** 查询指定用户的 Agent 运行记录。 */
    List<AgentRun> getAgentRunsByUserId(String userId);
    /** 按状态查询 Agent 运行记录。 */
    List<AgentRun> getAgentRunsByStatus(String status);
    /** 分页查询全部 Agent 运行记录。 */
    List<AgentRun> getAllAgentRuns(int page, int size);
    /** 统计 Agent 运行记录总数。 */
    long countAgentRuns();
    /** 更新指定运行的状态。 */
    boolean updateAgentRunStatus(String runId, String status);
    /** 查询运行记录及其步骤。 */
    AgentRunResponse getAgentRunWithSteps(String runId);
    /** 查询运行记录及其步骤、工具调用记录。 */
    AgentRunResponse getAgentRunWithStepsAndToolCalls(String runId);
}

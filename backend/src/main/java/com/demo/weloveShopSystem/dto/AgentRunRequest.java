package com.demo.weloveShopSystem.dto;

import lombok.Data;

/**
 * 发起一次 Agent 运行的请求参数。
 */
@Data
public class AgentRunRequest {
    /** Agent 运行唯一标识，用于追踪一次完整任务。 */
    private String runId;
    /** 链路追踪 ID，用于串联一次请求中的步骤和工具调用。 */
    private String traceId;
    /** 关联的会话 ID。 */
    private String conversationId;
    /** 发起任务的用户 ID。 */
    private String userId;
    /** 用户原始输入内容。 */
    private String input;
    /** Agent 需要完成的目标。 */
    private String goal;
    /** Agent 类型，例如购物助手、知识问答助手或后台助手。 */
    private String agentType;
    /** 执行任务时附带的上下文信息。 */
    private String context;
    /** 是否为管理员发起的 Agent 任务。 */
    private Boolean isAdmin;
}

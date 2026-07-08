package com.demo.weloveShopSystem.dto;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Agent 运行结果和运行过程详情。
 */
@Data
public class AgentRunResponse {
    /** 数据库记录 ID。 */
    private String id;
    /** Agent 运行唯一标识。 */
    private String runId;
    /** 链路追踪 ID。 */
    private String traceId;
    /** 关联的会话 ID。 */
    private String conversationId;
    /** 发起任务的用户 ID。 */
    private String userId;
    /** 运行状态，例如 running、success、failed、cancelled。 */
    private String status;
    /** 本次 Agent 运行目标。 */
    private String goal;
    /** 任务开始时间。 */
    private LocalDateTime startTime;
    /** 任务结束时间。 */
    private LocalDateTime endTime;
    /** 用户原始输入。 */
    private String input;
    /** Agent 最终输出。 */
    private String output;
    /** 失败时的错误信息。 */
    private String errorMessage;
    /** 失败时的错误码。 */
    private String errorCode;
    /** 记录创建时间。 */
    private LocalDateTime createdAt;
    /** 当前执行到的步骤下标。 */
    private Integer currentStepIndex;
    /** Agent 执行步骤列表。 */
    private List<AgentStepDTO> steps;
    /** Agent 调用外部工具的记录列表。 */
    private List<ToolCallDTO> toolCalls;
    /** Agent 执行过程中产生的中间结论。 */
    private List<IntermediateConclusionDTO> intermediateConclusions;
    /** 本次运行总耗时，通常单位为毫秒。 */
    private Long elapsedTime;
    /** 本次运行允许的最大步骤数。 */
    private Integer maxSteps;
    /** 本次运行超时时间，单位为秒。 */
    private Integer timeoutSeconds;
    /** 任务类型，例如 shopping、knowledge_qa、admin_copilot。 */
    private String taskType;
    /** 最终展示给用户的回答。 */
    private String answer;
    /** 回答引用的资料来源。 */
    private List<SourceDTO> sources;
    /** 是否存在引用来源。 */
    private Boolean hasSources;
}

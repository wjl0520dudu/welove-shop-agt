package com.demo.weloveShopSystem.dto;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Agent 执行过程中的单个步骤。
 */
@Data
public class AgentStepDTO {
    /** 步骤记录 ID。 */
    private String id;
    /** 所属 Agent 运行 ID。 */
    private String runId;
    /** 步骤名称，例如意图识别、商品检索、生成回答。 */
    private String stepName;
    /** 步骤状态，例如 running、success、failed。 */
    private String status;
    /** 该步骤的输入内容。 */
    private String input;
    /** 该步骤的输出内容。 */
    private String output;
    /** 该步骤失败时的错误信息。 */
    private String errorMessage;
    /** 步骤开始时间。 */
    private LocalDateTime startTime;
    /** 步骤结束时间。 */
    private LocalDateTime endTime;
    /** 步骤记录创建时间。 */
    private LocalDateTime createdAt;
}

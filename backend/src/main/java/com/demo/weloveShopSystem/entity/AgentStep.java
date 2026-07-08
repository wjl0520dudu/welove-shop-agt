package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Agent 执行步骤实体。
 */
@Data
@TableName("agent_step")
public class AgentStep {
    /** 步骤记录 ID，使用 UUID。 */
    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    /** 所属 Agent 运行 ID。 */
    private String runId;
    /** 步骤类型。 */
    private String stepType;
    /** 步骤名称。 */
    private String stepName;
    /** 步骤状态。 */
    private String status;
    /** 步骤输入。 */
    private String input;
    /** 步骤输出。 */
    private String output;
    /** 错误信息。 */
    private String errorMessage;
    /** 开始时间。 */
    private LocalDateTime startTime;
    /** 结束时间。 */
    private LocalDateTime endTime;
    /** 创建时间。 */
    private LocalDateTime createdAt;
    /** 步骤耗时，单位毫秒。 */
    private Long durationMs;
    /** 关联工具调用 ID。 */
    private String toolCallId;
}

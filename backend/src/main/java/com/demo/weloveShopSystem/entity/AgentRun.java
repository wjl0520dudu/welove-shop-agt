package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Agent 运行记录实体。
 */
@Data
@TableName("agent_run")
public class AgentRun {
    /** 数据库记录 ID，使用 UUID。 */
    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    /** Agent 运行唯一标识。 */
    private String runId;
    /** 链路追踪 ID。 */
    private String traceId;
    /** 关联会话 ID。 */
    private String conversationId;
    /** 发起用户 ID。 */
    private String userId;
    /** 运行状态。 */
    private String status;
    /** 运行目标。 */
    private String goal;
    /** 识别出的用户意图。 */
    private String intent;
    /** 开始时间。 */
    private LocalDateTime startTime;
    /** 结束时间。 */
    private LocalDateTime endTime;
    /** 输入内容。 */
    private String input;
    /** 输出内容。 */
    private String output;
    /** 错误信息。 */
    private String errorMessage;
    /** 错误码。 */
    private String errorCode;
    /** 创建时间。 */
    private LocalDateTime createdAt;
}

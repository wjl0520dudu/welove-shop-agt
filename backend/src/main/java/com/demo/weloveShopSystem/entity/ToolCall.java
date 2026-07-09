package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Agent 工具调用记录实体。
 */
@Data
@TableName("tool_call")
public class ToolCall {
    /** 工具调用记录 ID，使用 UUID。 */
    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    /** 工具调用唯一标识。 */
    private String toolCallId;
    /** 所属 Agent 运行 ID。 */
    private String runId;
    /** 工具名称。 */
    private String toolName;
    /** 输入参数。 */
    private String inputParams;
    /** 工具输出。 */
    private String output;
    /** 调用状态。 */
    private String status;
    /** 调用耗时，单位毫秒。 */
    private Long durationMs;
    /** 错误信息。 */
    private String errorMessage;
    /** 调用发生时间。 */
    private LocalDateTime timestamp;
    /** 创建时间。 */
    private LocalDateTime createdAt;
}

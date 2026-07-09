package com.demo.weloveShopSystem.dto;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Agent 调用外部工具的记录。
 */
@Data
public class ToolCallDTO {
    /** 数据库记录 ID。 */
    private String id;
    /** 工具调用唯一 ID。 */
    private String toolCallId;
    /** 所属 Agent 运行 ID。 */
    private String runId;
    /** 工具名称，例如 product_search、vector_search、cart_update。 */
    private String toolName;
    /** 调用工具时传入的参数，通常为 JSON 字符串。 */
    private String inputParams;
    /** 工具返回结果，通常为 JSON 字符串或文本。 */
    private String output;
    /** 调用状态，例如 success 或 failed。 */
    private String status;
    /** 工具调用耗时，单位毫秒。 */
    private Long durationMs;
    /** 工具调用失败时的错误信息。 */
    private String errorMessage;
    /** 工具调用发生时间。 */
    private LocalDateTime timestamp;
    /** 记录创建时间。 */
    private LocalDateTime createdAt;
}

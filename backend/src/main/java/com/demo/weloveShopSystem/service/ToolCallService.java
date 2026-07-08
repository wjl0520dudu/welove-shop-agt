package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.entity.ToolCall;

import java.util.List;

/**
 * Agent 工具调用记录服务接口。
 */
public interface ToolCallService {
    /** 保存工具调用记录。 */
    void saveToolCall(ToolCall toolCall);
    /** 查询指定 Agent 运行的工具调用记录。 */
    List<ToolCall> getToolCallsByRunId(String runId);
    /** 查询最近失败的工具调用记录。 */
    List<ToolCall> getFailedToolCalls(int limit);
    /** 分页查询全部工具调用记录。 */
    List<ToolCall> getAllToolCalls(int page, int size);
    /** 统计工具调用记录总数。 */
    long countToolCalls();
}

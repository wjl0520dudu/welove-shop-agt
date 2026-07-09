package com.demo.weloveShopSystem.controller.admin;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.AgentRun;
import com.demo.weloveShopSystem.entity.AgentStep;
import com.demo.weloveShopSystem.entity.ToolCall;
import com.demo.weloveShopSystem.mapper.AgentStepMapper;
import com.demo.weloveShopSystem.service.AgentRunService;
import com.demo.weloveShopSystem.service.ToolCallService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 后台 Agent 运行监控控制器。
 * <p>
 * 用来看每一次 Agent 从进入到结束的完整链路:run 元数据、每一步 step、
 * 每次 tool_call,以及最近失败的工具调用,是排查 AI 侧问题时最常用的入口。
 */
@RestController
@RequestMapping("/api/admin/agent")
@RequiredArgsConstructor
public class AgentAdminController {

    private final AgentRunService agentRunService;
    private final ToolCallService toolCallService;
    private final AgentStepMapper agentStepMapper;

    /**
     * Agent 运行记录列表。
     * <p>
     * status 与 userId 二选一优先,都不传就走分页;当前 status/userId 分支不带
     * 分页参数,后续如果规模变大可以在 Service 里补上,不影响接口签名。
     */
    @GetMapping("/runs")
    public Result<List<AgentRun>> getAgentRuns(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String userId) {
        if (status != null) {
            return Result.success(agentRunService.getAgentRunsByStatus(status));
        }
        if (userId != null) {
            return Result.success(agentRunService.getAgentRunsByUserId(userId));
        }
        return Result.success(agentRunService.getAllAgentRuns(page, size));
    }

    /** 查询指定 Agent 运行的元数据。 */
    @GetMapping("/runs/{runId}")
    public Result<AgentRun> getAgentRun(@PathVariable String runId) {
        AgentRun run = agentRunService.getAgentRunByRunId(runId);
        if (run == null) {
            return Result.error("运行记录不存在");
        }
        return Result.success(run);
    }

    /** 查询指定 Agent 运行的所有步骤,按 createdAt 正序,方便顺时序回放。 */
    @GetMapping("/runs/{runId}/steps")
    public Result<List<AgentStep>> getRunSteps(@PathVariable String runId) {
        List<AgentStep> steps = agentStepMapper.selectList(
                new LambdaQueryWrapper<AgentStep>()
                        .eq(AgentStep::getRunId, runId)
                        .orderByAsc(AgentStep::getCreatedAt));
        return Result.success(steps);
    }

    /** 工具调用记录分页列表。 */
    @GetMapping("/tool-calls")
    public Result<List<ToolCall>> getToolCalls(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size) {
        return Result.success(toolCallService.getAllToolCalls(page, size));
    }

    /** 最近失败的工具调用,便于快速定位失败最多的工具。 */
    @GetMapping("/tool-calls/failed")
    public Result<List<ToolCall>> getFailedToolCalls(
            @RequestParam(defaultValue = "10") int limit) {
        return Result.success(toolCallService.getFailedToolCalls(limit));
    }
}

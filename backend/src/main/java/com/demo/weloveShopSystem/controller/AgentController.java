package com.demo.weloveShopSystem.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.demo.weloveShopSystem.dto.AgentRunRequest;
import com.demo.weloveShopSystem.dto.AgentRunResponse;
import com.demo.weloveShopSystem.entity.AgentRun;
import com.demo.weloveShopSystem.entity.AgentStep;
import com.demo.weloveShopSystem.mapper.AgentRunMapper;
import com.demo.weloveShopSystem.mapper.AgentStepMapper;
import com.demo.weloveShopSystem.service.AgentRunService;
import com.demo.weloveShopSystem.service.AgentService;
import com.demo.weloveShopSystem.common.Result;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 用户侧 Agent 运行控制器。
 */
@RestController
@RequestMapping("/api/agent")
@RequiredArgsConstructor
@Slf4j
public class AgentController {

    private final AgentService agentService;
    private final AgentRunService agentRunService;
    private final AgentRunMapper agentRunMapper;
    private final AgentStepMapper agentStepMapper;

    /** 发起一次 Agent 运行。 */
    @PostMapping("/run")
    public AgentRunResponse runAgent(@RequestBody AgentRunRequest request) {
        return agentService.runAgent(request);
    }

    /** 分页查询当前用户的 Agent 运行记录。 */
    @GetMapping("/runs")
    public Result<IPage<AgentRun>> listRuns(
            @RequestParam(defaultValue = "1") Integer pageNum,
            @RequestParam(defaultValue = "10") Integer pageSize,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) LocalDateTime startTime,
            @RequestParam(required = false) LocalDateTime endTime) {
        // 从 JWT 获取 userId，避免越权查询其他用户运行记录。
        Long userId = Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());

        Page<AgentRun> page = new Page<>(pageNum, pageSize);
        LambdaQueryWrapper<AgentRun> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AgentRun::getUserId, userId);
        if (status != null && !status.isEmpty()) {
            wrapper.eq(AgentRun::getStatus, status);
        }
        if (startTime != null) {
            wrapper.ge(AgentRun::getStartTime, startTime);
        }
        if (endTime != null) {
            wrapper.le(AgentRun::getStartTime, endTime);
        }
        wrapper.orderByDesc(AgentRun::getStartTime);
        return Result.success(agentRunMapper.selectPage(page, wrapper));
    }

    /** 查询指定 Agent 运行详情。 */
    @GetMapping("/run/{runId}")
    public Result<AgentRun> getRun(@PathVariable String runId) {
        AgentRun agentRun = agentRunMapper.selectOne(
                new LambdaQueryWrapper<AgentRun>().eq(AgentRun::getRunId, runId));
        if (agentRun == null) {
            return Result.error("AgentRun 不存在");
        }
        return Result.success(agentRun);
    }

    /** 查询指定 Agent 运行的步骤列表。 */
    @GetMapping("/run/{runId}/steps")
    public Result<List<AgentStep>> getSteps(@PathVariable String runId) {
        return Result.success(agentStepMapper.selectList(
                new LambdaQueryWrapper<AgentStep>()
                        .eq(AgentStep::getRunId, runId)
                        .orderByAsc(AgentStep::getCreatedAt)));
    }

    /** 查询指定 Agent 运行的工具调用记录。 */
    @GetMapping("/run/{runId}/tool-calls")
    public Result<List<?>> getToolCalls(@PathVariable String runId) {
        return Result.success(List.of());
    }

    /** 删除指定 Agent 运行记录。 */
    @DeleteMapping("/run/{runId}")
    public Result<Void> deleteRun(@PathVariable String runId) {
        int deleted = agentRunMapper.delete(
                new LambdaQueryWrapper<AgentRun>().eq(AgentRun::getRunId, runId));
        if (deleted > 0) {
            return Result.success(null);
        }
        return Result.error("删除失败");
    }
}

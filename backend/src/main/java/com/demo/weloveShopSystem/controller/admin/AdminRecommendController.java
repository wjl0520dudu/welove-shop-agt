package com.demo.weloveShopSystem.controller.admin;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.RecommendationLog;
import com.demo.weloveShopSystem.mapper.RecommendationLogMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 后台推荐效果统计控制器。
 * <p>
 * user_feedback 语义:1=不满意 2=满意 null=未反馈。
 */
@RestController
@RequestMapping("/api/admin/recommend")
@RequiredArgsConstructor
public class AdminRecommendController {

    private final RecommendationLogMapper recommendationLogMapper;

    /**
     * 推荐点击率、满意度、未反馈率的统计概览。
     * 百分比一律取整,便于前端直接展示,不给小数点。
     */
    @GetMapping("/stats")
    public Result<Map<String, Object>> stats() {
        long total = recommendationLogMapper.selectCount(null);
        long clicked = recommendationLogMapper.selectCount(
                new LambdaQueryWrapper<RecommendationLog>()
                        .eq(RecommendationLog::getUserClicked, true));
        long satisfied = recommendationLogMapper.selectCount(
                new LambdaQueryWrapper<RecommendationLog>()
                        .eq(RecommendationLog::getUserFeedback, 2));
        long dissatisfied = recommendationLogMapper.selectCount(
                new LambdaQueryWrapper<RecommendationLog>()
                        .eq(RecommendationLog::getUserFeedback, 1));
        long noFeedback = total - satisfied - dissatisfied;

        Map<String, Object> result = new HashMap<>();
        result.put("totalRecommendations", total);
        result.put("clickRate", total > 0 ? Math.round(clicked * 100.0 / total) : 0);
        result.put("satisfactionRate", total > 0 ? Math.round(satisfied * 100.0 / total) : 0);
        result.put("noFeedbackRate", total > 0 ? Math.round(noFeedback * 100.0 / total) : 0);
        result.put("clickedCount", clicked);
        result.put("satisfiedCount", satisfied);
        result.put("noFeedbackCount", noFeedback);
        return Result.success(result);
    }

    /** 分页查询推荐日志,按 createTime 倒序。 */
    @GetMapping("/logs")
    public Result<IPage<RecommendationLog>> listLogs(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        LambdaQueryWrapper<RecommendationLog> wrapper = new LambdaQueryWrapper<>();
        wrapper.orderByDesc(RecommendationLog::getCreateTime);
        return Result.success(recommendationLogMapper.selectPage(new Page<>(page, size), wrapper));
    }
}

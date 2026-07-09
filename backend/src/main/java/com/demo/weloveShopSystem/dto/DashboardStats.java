package com.demo.weloveShopSystem.dto;

import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 后台仪表盘统计数据。
 * <p>
 * 字段分两段:
 *  1) 通用指标(用户数/文档数/问答数/命中率、未答问题、问题趋势)
 *  2) 电商导购指标(今日对话、今日推荐、点击率、满意度、意图分布、
 *     近 7 日对话趋势、热门商品、最近推荐)
 * <p>
 * Map<String, Object> 保留一定灵活度,便于前端后续扩展字段时无需改后端 DTO。
 */
@Data
public class DashboardStats {

    // ---------- 通用指标 ----------
    /** 用户总数。 */
    private Long userCount;
    /** 知识库文档总数。 */
    private Long docCount;
    /** 问答日志总数。 */
    private Long qaCount;
    /** 知识库命中率,取值 [0, 100],百分比。 */
    private Double hitRate;
    /** 未回答问题 TopN,每条通常包含 question + count。 */
    private List<Map<String, Object>> unansweredQuestions;
    /** 近 7 日按日聚合的问题数量趋势。 */
    private List<Map<String, Object>> questionTrends;

    // ---------- 电商导购指标 ----------
    /** 今日对话数。 */
    private Long todayConversations;
    /** 今日推荐次数。 */
    private Long todayRecommendations;
    /** 推荐点击率,click / total,百分比。 */
    private Double clickRate;
    /** 用户满意度,positive / feedbackTotal,百分比。 */
    private Double satisfactionRate;
    /** 意图分布,key 为意图名,value 为出现次数。 */
    private Map<String, Long> intentDistribution;
    /** 近 7 日对话趋势,每项通常包含 date + count。 */
    private List<Map<String, Object>> dailyTrends;
    /** 热门商品,按销量排序。 */
    private List<Map<String, Object>> hotProducts;
    /** 最近推荐记录。 */
    private List<Map<String, Object>> recentRecommendations;
}

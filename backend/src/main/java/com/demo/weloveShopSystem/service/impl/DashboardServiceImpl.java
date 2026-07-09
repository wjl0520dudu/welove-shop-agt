package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.demo.weloveShopSystem.dto.DashboardStats;
import com.demo.weloveShopSystem.entity.AgentRun;
import com.demo.weloveShopSystem.entity.Conversation;
import com.demo.weloveShopSystem.entity.KnowledgeDoc;
import com.demo.weloveShopSystem.entity.Product;
import com.demo.weloveShopSystem.entity.QaLog;
import com.demo.weloveShopSystem.entity.QaUnanswered;
import com.demo.weloveShopSystem.entity.RecommendationLog;
import com.demo.weloveShopSystem.entity.User;
import com.demo.weloveShopSystem.mapper.AgentRunMapper;
import com.demo.weloveShopSystem.mapper.ConversationMapper;
import com.demo.weloveShopSystem.mapper.KnowledgeDocMapper;
import com.demo.weloveShopSystem.mapper.ProductMapper;
import com.demo.weloveShopSystem.mapper.QaLogMapper;
import com.demo.weloveShopSystem.mapper.QaUnansweredMapper;
import com.demo.weloveShopSystem.mapper.RecommendationLogMapper;
import com.demo.weloveShopSystem.mapper.UserMapper;
import com.demo.weloveShopSystem.service.DashboardService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 后台仪表盘统计服务实现。
 * <p>
 * 每个指标封装成独立私有方法,便于后续拆分为并行查询或引入缓存;
 * 命中率与点击率一律返回百分比 [0, 100]。
 */
@Service
@RequiredArgsConstructor
public class DashboardServiceImpl implements DashboardService {

    private final UserMapper userMapper;
    private final KnowledgeDocMapper docMapper;
    private final QaLogMapper qaLogMapper;
    private final QaUnansweredMapper qaUnansweredMapper;
    private final ConversationMapper conversationMapper;
    private final RecommendationLogMapper recommendationLogMapper;
    private final ProductMapper productMapper;
    private final AgentRunMapper agentRunMapper;

    /** 排除掉的管理类意图,不在意图分布里展示,避免管理员操作污染 C 端画像。 */
    private static final Set<String> ADMIN_INTENTS = Set.of("admin_copilot", "knowledge_inspection");

    @Override
    public DashboardStats getStats() {
        DashboardStats stats = new DashboardStats();

        stats.setUserCount(userMapper.selectCount(new QueryWrapper<User>()));
        stats.setDocCount(docMapper.selectCount(new QueryWrapper<KnowledgeDoc>()));

        long totalQa = qaLogMapper.selectCount(new QueryWrapper<QaLog>());
        stats.setQaCount(totalQa);
        stats.setHitRate(calculateHitRate(totalQa));
        stats.setUnansweredQuestions(getTopUnansweredQuestions());
        stats.setQuestionTrends(getQuestionTrends());

        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        stats.setTodayConversations(countTodayConversations(todayStart));
        stats.setTodayRecommendations(countTodayRecommendations(todayStart));
        stats.setClickRate(calculateClickRate());
        stats.setSatisfactionRate(calculateSatisfactionRate());
        stats.setIntentDistribution(getIntentDistribution());
        stats.setDailyTrends(getDailyTrends());
        stats.setHotProducts(getHotProducts());
        stats.setRecentRecommendations(getRecentRecommendations());
        return stats;
    }

    // ---------- 通用指标 ----------

    private Double calculateHitRate(long totalQa) {
        if (totalQa == 0) {
            return 0.0;
        }
        QueryWrapper<QaUnanswered> unansweredQuery = new QueryWrapper<>();
        unansweredQuery.select("sum(count)");
        List<Object> sumResult = qaUnansweredMapper.selectObjs(unansweredQuery);
        long unansweredTotal = 0;
        if (sumResult != null && !sumResult.isEmpty() && sumResult.get(0) != null) {
            unansweredTotal = Long.parseLong(sumResult.get(0).toString());
        }
        long answered = Math.max(0, totalQa - unansweredTotal);
        return (double) answered / totalQa * 100;
    }

    private List<Map<String, Object>> getTopUnansweredQuestions() {
        QueryWrapper<QaUnanswered> wrapper = new QueryWrapper<>();
        wrapper.orderByDesc("count").last("limit 5");
        List<QaUnanswered> unansweredList = qaUnansweredMapper.selectList(wrapper);

        List<Map<String, Object>> result = new ArrayList<>();
        for (QaUnanswered unanswered : unansweredList) {
            Map<String, Object> item = new HashMap<>();
            item.put("question", unanswered.getQuestion());
            item.put("count", unanswered.getCount());
            result.add(item);
        }
        return result;
    }

    private List<Map<String, Object>> getQuestionTrends() {
        QueryWrapper<QaLog> wrapper = new QueryWrapper<>();
        wrapper.select("DATE_FORMAT(create_time, '%Y-%m-%d') as date", "count(*) as count")
                .ge("create_time", LocalDateTime.now().minusDays(7))
                .groupBy("date")
                .orderByAsc("date");
        return qaLogMapper.selectMaps(wrapper);
    }

    // ---------- 电商导购指标 ----------

    private Long countTodayConversations(LocalDateTime todayStart) {
        QueryWrapper<Conversation> wrapper = new QueryWrapper<>();
        wrapper.ge("create_time", todayStart);
        return conversationMapper.selectCount(wrapper);
    }

    private Long countTodayRecommendations(LocalDateTime todayStart) {
        QueryWrapper<RecommendationLog> wrapper = new QueryWrapper<>();
        wrapper.ge("create_time", todayStart);
        return recommendationLogMapper.selectCount(wrapper);
    }

    private Double calculateClickRate() {
        long totalRecs = recommendationLogMapper.selectCount(new QueryWrapper<>());
        if (totalRecs == 0) {
            return 0.0;
        }
        QueryWrapper<RecommendationLog> wrapper = new QueryWrapper<>();
        wrapper.eq("user_clicked", true);
        long clickedCount = recommendationLogMapper.selectCount(wrapper);
        return (double) clickedCount / totalRecs * 100;
    }

    private Double calculateSatisfactionRate() {
        QueryWrapper<RecommendationLog> feedbackWrapper = new QueryWrapper<>();
        feedbackWrapper.isNotNull("user_feedback");
        long feedbackCount = recommendationLogMapper.selectCount(feedbackWrapper);
        if (feedbackCount == 0) {
            return 0.0;
        }
        QueryWrapper<RecommendationLog> satisfiedWrapper = new QueryWrapper<>();
        satisfiedWrapper.eq("user_feedback", 1);
        long satisfiedCount = recommendationLogMapper.selectCount(satisfiedWrapper);
        return (double) satisfiedCount / feedbackCount * 100;
    }

    private Map<String, Long> getIntentDistribution() {
        QueryWrapper<AgentRun> wrapper = new QueryWrapper<>();
        wrapper.select("intent", "count(*) as count")
                .isNotNull("intent")
                .groupBy("intent");
        List<Map<String, Object>> intentList = agentRunMapper.selectMaps(wrapper);

        Map<String, Long> intentMap = new HashMap<>();
        for (Map<String, Object> item : intentList) {
            Object intentValue = item.get("intent");
            Object countValue = item.get("count");
            if (intentValue != null && countValue instanceof Number) {
                String intent = intentValue.toString();
                if (!ADMIN_INTENTS.contains(intent)) {
                    intentMap.put(intent, ((Number) countValue).longValue());
                }
            }
        }
        return intentMap;
    }

    private List<Map<String, Object>> getDailyTrends() {
        QueryWrapper<Conversation> wrapper = new QueryWrapper<>();
        wrapper.select("DATE_FORMAT(create_time, '%Y-%m-%d') as date", "count(*) as count")
                .ge("create_time", LocalDateTime.now().minusDays(7))
                .groupBy("date")
                .orderByAsc("date");
        return conversationMapper.selectMaps(wrapper);
    }

    private List<Map<String, Object>> getHotProducts() {
        QueryWrapper<Product> wrapper = new QueryWrapper<>();
        wrapper.select("title", "brand", "base_price", "image_url", "sales_count", "rating")
                .orderByDesc("sales_count")
                .last("limit 5");
        return productMapper.selectMaps(wrapper);
    }

    private List<Map<String, Object>> getRecentRecommendations() {
        QueryWrapper<RecommendationLog> wrapper = new QueryWrapper<>();
        wrapper.orderByDesc("create_time").last("limit 5");
        List<RecommendationLog> recentList = recommendationLogMapper.selectList(wrapper);

        List<Map<String, Object>> result = new ArrayList<>();
        for (RecommendationLog log : recentList) {
            Map<String, Object> item = new HashMap<>();
            item.put("id", log.getId());
            item.put("query", log.getQuery());
            item.put("intent", log.getIntent());
            item.put("recommendedProductIds", log.getRecommendedProductIds());
            item.put("userClicked", log.getUserClicked());
            item.put("userFeedback", log.getUserFeedback());
            item.put("createTime", log.getCreateTime());
            result.add(item);
        }
        return result;
    }
}

package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.entity.RecommendationLog;

/**
 * 推荐日志服务接口。
 */
public interface RecommendationLogService {
    /** 保存推荐日志。 */
    void save(RecommendationLog log);
    /** 更新用户对推荐结果的反馈。 */
    void updateFeedback(Long id, Integer feedback);
}

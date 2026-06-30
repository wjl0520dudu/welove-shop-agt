package com.demo.weloveShopSystem.service.impl;


import com.demo.weloveShopSystem.entity.RecommendationLog;
import com.demo.weloveShopSystem.mapper.RecommendationLogMapper;
import com.demo.weloveShopSystem.service.RecommendationLogService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class RecommendationLogServiceImpl implements RecommendationLogService {

    private final RecommendationLogMapper recommendationLogMapper;

    @Override
    public void save(RecommendationLog log) {
        recommendationLogMapper.insert(log);
    }

    @Override
    public void updateFeedback(Long id, Integer feedback) {
        RecommendationLog log = recommendationLogMapper.selectById(id);
        if (log != null) {
            log.setUserFeedback(feedback);
            recommendationLogMapper.updateById(log);
        }
    }
}

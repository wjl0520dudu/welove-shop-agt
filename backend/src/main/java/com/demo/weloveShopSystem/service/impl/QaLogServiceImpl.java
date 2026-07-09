package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.demo.weloveShopSystem.entity.QaLog;
import com.demo.weloveShopSystem.mapper.QaLogMapper;
import com.demo.weloveShopSystem.service.QaLogService;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;

/**
 * QaLog 服务实现。
 * <p>
 * log() 使用 @Async 异步落库,避免占用问答主链路耗时;主应用已 @EnableAsync,
 * 无需额外线程池配置(默认 SimpleAsyncTaskExecutor 已够用,后续需要限流再抽出去)。
 */
@Service
public class QaLogServiceImpl extends ServiceImpl<QaLogMapper, QaLog> implements QaLogService {

    @Override
    @Async
    public void log(Long userId, String question, String answer) {
        QaLog log = new QaLog();
        log.setUserId(userId);
        log.setQuestion(question);
        log.setAnswer(answer);
        log.setCreateTime(LocalDateTime.now());
        this.save(log);
    }
}

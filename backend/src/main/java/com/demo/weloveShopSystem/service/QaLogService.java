package com.demo.weloveShopSystem.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.demo.weloveShopSystem.entity.QaLog;

/**
 * AI 问答日志服务接口。
 * <p>
 * 提供最小的 log(userId, question, answer) 语义;更复杂的耗时/反馈字段
 * 由 AiService 侧填充后再调用 IService.updateById 更新,以避免这里方法膨胀。
 */
public interface QaLogService extends IService<QaLog> {

    /**
     * 异步记录一次用户问答,不阻塞主流程。
     *
     * @param userId   提问用户 ID
     * @param question 用户问题原文
     * @param answer   AI 回答原文
     */
    void log(Long userId, String question, String answer);
}

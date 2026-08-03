package com.welove.shop.chat.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.welove.shop.chat.entity.ConversationContext;
import com.welove.shop.chat.entity.Message;
import com.welove.shop.chat.mapper.ConversationContextMapper;
import com.welove.shop.chat.mapper.MessageMapper;
import com.welove.shop.chat.service.ConversationContextService;
import com.welove.shop.common.core.util.JsonUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** 双层记忆:Redis 短期缓存 + PG 长期存储。 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ConversationContextServiceImpl implements ConversationContextService {
    private static final String REDIS_PREFIX = "conversation_context:";
    private final MessageMapper messageMapper;
    private final ConversationContextMapper ctxMapper;
    private final StringRedisTemplate redisTemplate;

    @Value("${chat-service.context.redis-ttl-seconds:1800}") private long redisTtl;
    @Value("${chat-service.context.window-size:10}") private int windowSize;

    @Override
    public List<Message> getConversationContext(Long conversationId, int maxMessages) {
        String key = REDIS_PREFIX + conversationId;
        String cached = redisTemplate.opsForValue().get(key);
        if (cached != null) {
            try {
                return JsonUtil.fromJson(cached, new TypeReference<List<Message>>() {});
            } catch (Exception e) { log.debug("cache parse fail, fallback db"); }
        }
        int limit = maxMessages > 0 ? maxMessages : windowSize;
        List<Message> msgs = messageMapper.selectList(
                new LambdaQueryWrapper<Message>()
                        .eq(Message::getConversationId, conversationId)
                        .orderByDesc(Message::getCreateTime)
                        .last("LIMIT " + limit));
        Collections.reverse(msgs);
        redisTemplate.opsForValue().set(key, JsonUtil.toJson(msgs), redisTtl, TimeUnit.SECONDS);
        return msgs;
    }

    @Override
    public void updateConversationContext(Long conversationId, Long userId, Message newMessage) {
        invalidateConversationContext(conversationId);
        ConversationContext ctx = new ConversationContext();
        ctx.setConversationId(conversationId);
        ctx.setUserId(userId);
        ctx.setWindowSize(windowSize);
        ctx.setImportanceScore(0.5);
        ctx.setUpdateTime(LocalDateTime.now());
        ctx.setCreateTime(LocalDateTime.now());
        ctxMapper.upsertActivity(ctx);
    }

    @Override
    public void invalidateConversationContext(Long conversationId) {
        redisTemplate.delete(REDIS_PREFIX + conversationId);
    }

    @Override
    public ConversationContext getRollingSummaryContext(Long conversationId) {
        return ctxMapper.selectByConversationId(conversationId);
    }

    @Override
    public boolean updateRollingSummary(Long conversationId, String summary, Long coveredMessageId) {
        if (conversationId == null || coveredMessageId == null || summary == null || summary.isBlank()) {
            return false;
        }
        return ctxMapper.updateRollingSummary(conversationId, summary, coveredMessageId) > 0;
    }

    @Override
    public void cleanupExpiredContexts(int days) {
        // 按 updateTime + importance 清理,骨架期暂空
    }
}

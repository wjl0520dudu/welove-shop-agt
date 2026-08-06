package com.welove.shop.chat.service.impl;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;

/**
 * Serializes one visible assistant turn per conversation across chat-service
 * instances.  A JVM-local lock is deliberately insufficient once the service
 * is horizontally deployed, so ownership lives in Redis and is released with
 * a compare-and-delete Lua script.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ConversationTurnGuard {
    private static final String LOCK_PREFIX = "chat:conversation:turn-lock:";
    private static final DefaultRedisScript<Long> RELEASE_IF_OWNER = new DefaultRedisScript<>(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            Long.class
    );

    private final StringRedisTemplate redisTemplate;

    /** Must outlive the server-side SSE timeout; terminal callbacks release earlier in normal cases. */
    @Value("${chat-service.concurrency.turn-lock-lease-millis:330000}")
    private long leaseMillis;

    public boolean tryAcquire(Long conversationId, String ownerToken) {
        if (conversationId == null || ownerToken == null || ownerToken.isBlank()) {
            return false;
        }
        Boolean acquired = redisTemplate.opsForValue().setIfAbsent(
                lockKey(conversationId), ownerToken,
                Duration.ofMillis(Math.max(1_000L, leaseMillis))
        );
        return Boolean.TRUE.equals(acquired);
    }

    public boolean isOwnedBy(Long conversationId, String ownerToken) {
        if (conversationId == null || ownerToken == null || ownerToken.isBlank()) {
            return false;
        }
        return ownerToken.equals(redisTemplate.opsForValue().get(lockKey(conversationId)));
    }

    public void release(Long conversationId, String ownerToken) {
        if (conversationId == null || ownerToken == null || ownerToken.isBlank()) {
            return;
        }
        try {
            redisTemplate.execute(RELEASE_IF_OWNER, List.of(lockKey(conversationId)), ownerToken);
        } catch (Exception ex) {
            // The lease prevents a permanent lock.  Do not hide the already-persisted terminal state.
            log.warn("conversation turn lock release failed conv={}: {}", conversationId, ex.getMessage());
        }
    }

    private static String lockKey(Long conversationId) {
        return LOCK_PREFIX + conversationId;
    }
}

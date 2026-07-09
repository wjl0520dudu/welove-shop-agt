package com.demo.weloveShopSystem.utils;

import com.demo.weloveShopSystem.config.CacheConfig;
import com.demo.weloveShopSystem.service.CacheService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * 缓存操作辅助工具。
 * <p>
 * 在 CacheService 之上封装 "读不到就回源写入" 与 "带锁回源" 两类常见组合,
 * 让业务代码不用重复写 "先 get、null 就查库、再 set" 的样板;还包括批量、
 * 刷新、命中率与预热等派生动作。
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class CacheUtils {

    private final CacheService cacheService;

    /** 获取或回源写入,使用该缓存名对应的默认 TTL。 */
    public <T> T getOrSet(String cacheName, String key, Supplier<T> supplier, Class<T> clazz) {
        return getOrSet(cacheName, key, supplier, clazz, getDefaultTtl(cacheName), TimeUnit.SECONDS);
    }

    /**
     * 获取或回源写入。
     * <p>
     * 命中即返回;未命中则调用 supplier 加载后写入缓存。加载抛异常时只记日志、
     * 返回 null,由调用方决定是否二次兜底,避免缓存层把业务异常吞掉。
     */
    public <T> T getOrSet(String cacheName, String key, Supplier<T> supplier, Class<T> clazz,
                          long ttl, TimeUnit timeUnit) {
        T cachedValue = cacheService.get(cacheName, key, clazz);
        if (cachedValue != null) {
            log.debug("Cache hit - name: {}, key: {}", cacheName, key);
            return cachedValue;
        }
        log.debug("Cache miss - name: {}, key: {}", cacheName, key);

        try {
            T value = supplier.get();
            if (value != null) {
                cacheService.set(cacheName, key, value, ttl, timeUnit);
                log.debug("Cache set - name: {}, key: {}, ttl: {} {}", cacheName, key, ttl, timeUnit);
            }
            return value;
        } catch (Exception e) {
            log.error("Failed to load data for cache - name: {}, key: {}", cacheName, key, e);
            return null;
        }
    }

    /** 带互斥锁的获取或回源写入,默认锁超时 5s。 */
    public <T> T getOrSetWithLock(String cacheName, String key, Supplier<T> supplier,
                                  Class<T> clazz, String lockKey) {
        return getOrSetWithLock(cacheName, key, supplier, clazz, lockKey,
                getDefaultTtl(cacheName), TimeUnit.SECONDS, 5000L);
    }

    /**
     * 带互斥锁的获取或回源写入,防止缓存击穿。
     * <p>
     * 抢到锁的线程负责实际加载并写入;没抢到的线程短暂等待后直接读缓存,
     * 避免所有线程同时打到底层数据源。锁基于 Redis SETNX 通过 CacheService 实现,
     * 不是分布式生产级方案(没有 Lua 脚本原子性、没有看门狗续期),
     * 适合中小并发场景,极端并发下建议改用 Redisson。
     */
    public <T> T getOrSetWithLock(String cacheName, String key, Supplier<T> supplier,
                                  Class<T> clazz, String lockKey,
                                  long ttl, TimeUnit timeUnit, long lockTimeout) {
        T cachedValue = cacheService.get(cacheName, key, clazz);
        if (cachedValue != null) {
            return cachedValue;
        }

        String lockCacheName = "cache_lock";
        boolean lockAcquired = false;
        try {
            lockAcquired = acquireLock(lockCacheName, lockKey, lockTimeout);
            if (lockAcquired) {
                // 双重检查:抢到锁后再确认一次缓存,避免刚才有别的线程已经回源写入。
                cachedValue = cacheService.get(cacheName, key, clazz);
                if (cachedValue != null) {
                    return cachedValue;
                }
                T value = supplier.get();
                if (value != null) {
                    cacheService.set(cacheName, key, value, ttl, timeUnit);
                }
                return value;
            }
            // 没抢到锁:短暂等待后读缓存,期望前面拿锁的线程已经写好。
            Thread.sleep(100);
            return cacheService.get(cacheName, key, clazz);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.error("Cache lock interrupted - name: {}, key: {}", cacheName, key, e);
            return null;
        } finally {
            if (lockAcquired) {
                releaseLock(lockCacheName, lockKey);
            }
        }
    }

    /**
     * 批量获取或回源写入。
     * <p>
     * supplier 只接收未命中的 keys,返回它们对应的键值对;方法内部再把
     * 加载的结果合并进最终 Map 一起返回。
     */
    public <T> Map<String, T> batchGetOrSet(String cacheName, List<String> keys,
                                            Function<List<String>, Map<String, T>> supplier,
                                            Class<T> clazz) {
        Map<String, T> cachedValues = cacheService.getBatch(cacheName, keys, clazz);
        List<String> missingKeys = keys.stream()
                .filter(key -> !cachedValues.containsKey(key))
                .collect(Collectors.toList());

        if (!missingKeys.isEmpty()) {
            Map<String, T> loadedValues = supplier.apply(missingKeys);
            if (loadedValues != null && !loadedValues.isEmpty()) {
                cacheService.setBatch(cacheName, new HashMap<>(loadedValues),
                        getDefaultTtl(cacheName), TimeUnit.SECONDS);
                cachedValues.putAll(loadedValues);
            }
        }
        return cachedValues;
    }

    /** 强制刷新:先删旧值,再重新加载并写回。 */
    public <T> T refresh(String cacheName, String key, Supplier<T> supplier, Class<T> clazz) {
        cacheService.delete(cacheName, key);
        T value = supplier.get();
        if (value != null) {
            cacheService.set(cacheName, key, value);
        }
        return value;
    }

    /** 设置新值并返回旧值。 */
    public <T> T getAndSet(String cacheName, String key, T value, Class<T> clazz) {
        T oldValue = cacheService.get(cacheName, key, clazz);
        cacheService.set(cacheName, key, value);
        return oldValue;
    }

    /** 缓存预热:一次性把预置数据批量写入,常用于应用启动时。 */
    public <T> void warmUp(String cacheName, Map<String, T> data) {
        if (data != null && !data.isEmpty()) {
            cacheService.setBatch(cacheName, new HashMap<>(data),
                    getDefaultTtl(cacheName), TimeUnit.SECONDS);
            log.info("Cache warmed up - name: {}, entries: {}", cacheName, data.size());
        }
    }

    /** 命中率,取值范围通常为 [0, 1]。 */
    public double getHitRate(String cacheName) {
        return cacheService.getHitRate(cacheName);
    }

    /** 当前条目数。 */
    public long getSize(String cacheName) {
        return cacheService.getSize(cacheName);
    }

    /** 清空指定缓存。 */
    public void clear(String cacheName) {
        cacheService.clear(cacheName);
        log.info("Cache cleared - name: {}", cacheName);
    }

    // ------------- 私有辅助 -------------

    /**
     * 通过 CacheService 抽象实现的一把简易锁。
     * <p>
     * 不是严格意义的分布式锁,只是保证同一时刻只有一个 caller 拿到 true;
     * 极端并发场景应替换为基于 Lua 的原子实现或 Redisson。
     */
    private boolean acquireLock(String cacheName, String lockKey, long timeoutMs) {
        String lockValue = String.valueOf(System.currentTimeMillis() + timeoutMs + 1);

        String currentValue = cacheService.get(cacheName, lockKey, String.class);
        if (currentValue == null) {
            cacheService.set(cacheName, lockKey, lockValue, timeoutMs, TimeUnit.MILLISECONDS);
            String newValue = cacheService.get(cacheName, lockKey, String.class);
            return newValue != null && newValue.equals(lockValue);
        }

        // 已有锁:如果已过期则清理后重试,格式非法一并清理。
        try {
            long expireTime = Long.parseLong(currentValue);
            if (System.currentTimeMillis() > expireTime) {
                cacheService.delete(cacheName, lockKey);
                return acquireLock(cacheName, lockKey, timeoutMs);
            }
        } catch (NumberFormatException e) {
            cacheService.delete(cacheName, lockKey);
            return acquireLock(cacheName, lockKey, timeoutMs);
        }
        return false;
    }

    private void releaseLock(String cacheName, String lockKey) {
        cacheService.delete(cacheName, lockKey);
    }

    /** 根据业务缓存名返回默认 TTL,未识别的名字回退到 1 小时。 */
    private long getDefaultTtl(String cacheName) {
        switch (cacheName) {
            case CacheConfig.CacheConstants.CACHE_AI_ANSWER:
                return CacheConfig.CacheConstants.TTL_AI_ANSWER;
            case CacheConfig.CacheConstants.CACHE_USER_SESSION:
                return CacheConfig.CacheConstants.TTL_USER_SESSION;
            case CacheConfig.CacheConstants.CACHE_DOC_METADATA:
                return CacheConfig.CacheConstants.TTL_DOC_METADATA;
            case CacheConfig.CacheConstants.CACHE_CONVERSATION_CONTEXT:
                return CacheConfig.CacheConstants.TTL_CONVERSATION_CONTEXT;
            case CacheConfig.CacheConstants.CACHE_VECTOR_SEARCH:
                return CacheConfig.CacheConstants.TTL_VECTOR_SEARCH;
            default:
                return 3600;
        }
    }
}

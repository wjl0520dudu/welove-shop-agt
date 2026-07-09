package com.demo.weloveShopSystem.controller;

import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.config.CacheConfig;
import com.demo.weloveShopSystem.service.CacheService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 缓存管理控制器。
 * <p>
 * 面向运维/管理员场景,提供缓存的观测(stats/info/config/health)与写操作
 * (删除单键、清空、刷新、批量删除/存在性检查),便于线上排查与热点数据维护。
 * 所有响应统一包在 Result 里,方便前端复用同一套响应处理逻辑。
 */
@RestController
@RequestMapping("/api/cache")
@RequiredArgsConstructor
@Slf4j
public class CacheController {

    private final CacheService cacheService;

    /** 汇总所有已注册缓存的统计信息。 */
    @GetMapping("/stats")
    public Result<Map<String, Object>> getCacheStats() {
        Map<String, Object> result = new HashMap<>();
        List<String> cacheNames = cacheService.getCacheNames();

        Map<String, Object> cacheStats = new HashMap<>();
        for (String cacheName : cacheNames) {
            Map<String, Object> stats = cacheService.getStats(cacheName);
            stats.put("size", cacheService.getSize(cacheName));
            stats.put("hitRate", cacheService.getHitRate(cacheName));
            cacheStats.put(cacheName, stats);
        }
        result.put("cacheStats", cacheStats);
        result.put("totalCaches", cacheNames.size());
        result.put("timestamp", System.currentTimeMillis());
        return Result.success(result);
    }

    /** 查询指定缓存的详情(统计 + 前 100 个 key,避免一次拉太多)。 */
    @GetMapping("/{cacheName}/info")
    public Result<Map<String, Object>> getCacheInfo(@PathVariable String cacheName) {
        Map<String, Object> result = new HashMap<>();
        result.put("cacheName", cacheName);
        result.put("stats", cacheService.getStats(cacheName));
        result.put("size", cacheService.getSize(cacheName));
        result.put("hitRate", cacheService.getHitRate(cacheName));

        Set<String> keys = cacheService.keys(cacheName, "*");
        if (keys != null && !keys.isEmpty()) {
            List<String> keyList = keys.stream().limit(100).collect(Collectors.toList());
            result.put("keys", keyList);
            result.put("totalKeys", keys.size());
        }
        return Result.success(result);
    }

    /** 查看指定缓存键的值与剩余过期时间。 */
    @GetMapping("/{cacheName}/key/{key}")
    public Result<Map<String, Object>> getCacheValue(
            @PathVariable String cacheName,
            @PathVariable String key) {
        Map<String, Object> result = new HashMap<>();

        boolean exists = cacheService.exists(cacheName, key);
        result.put("exists", exists);
        if (exists) {
            Object value = cacheService.get(cacheName, key, Object.class);
            Long expire = cacheService.getExpire(cacheName, key);
            result.put("value", value);
            result.put("expireSeconds", expire);
        }
        return Result.success(result);
    }

    /** 删除指定缓存键。 */
    @DeleteMapping("/{cacheName}/key/{key}")
    public Result<Map<String, Object>> deleteCacheKey(
            @PathVariable String cacheName,
            @PathVariable String key) {
        Map<String, Object> result = new HashMap<>();

        boolean existed = cacheService.exists(cacheName, key);
        cacheService.delete(cacheName, key);

        result.put("cacheName", cacheName);
        result.put("key", key);
        result.put("existed", existed);
        log.info("Cache key deleted - name: {}, key: {}", cacheName, key);
        return Result.success(result);
    }

    /** 清空指定缓存,返回清空前的条目数。 */
    @DeleteMapping("/{cacheName}")
    public Result<Map<String, Object>> clearCache(@PathVariable String cacheName) {
        Map<String, Object> result = new HashMap<>();

        long sizeBefore = cacheService.getSize(cacheName);
        cacheService.clear(cacheName);

        result.put("cacheName", cacheName);
        result.put("clearedEntries", sizeBefore);
        log.info("Cache cleared - name: {}, cleared entries: {}", cacheName, sizeBefore);
        return Result.success(result);
    }

    /** 刷新缓存:当前实现是清空后等待下次请求触发回源加载。 */
    @PostMapping("/{cacheName}/refresh")
    public Result<Map<String, Object>> refreshCache(@PathVariable String cacheName) {
        Map<String, Object> result = new HashMap<>();

        long sizeBefore = cacheService.getSize(cacheName);
        cacheService.clear(cacheName);

        result.put("cacheName", cacheName);
        result.put("clearedEntries", sizeBefore);
        result.put("message", "Cache cleared. New data will be loaded on next request.");
        log.info("Cache refreshed - name: {}, cleared entries: {}", cacheName, sizeBefore);
        return Result.success(result);
    }

    /** 展示缓存配置:名称常量、TTL、容量上限、当前所有缓存名。 */
    @GetMapping("/config")
    public Result<Map<String, Object>> getCacheConfig() {
        Map<String, Object> config = new HashMap<>();

        Map<String, Object> constants = new HashMap<>();
        constants.put("CACHE_AI_ANSWER", CacheConfig.CacheConstants.CACHE_AI_ANSWER);
        constants.put("CACHE_USER_SESSION", CacheConfig.CacheConstants.CACHE_USER_SESSION);
        constants.put("CACHE_DOC_METADATA", CacheConfig.CacheConstants.CACHE_DOC_METADATA);
        constants.put("CACHE_CONVERSATION_CONTEXT", CacheConfig.CacheConstants.CACHE_CONVERSATION_CONTEXT);
        constants.put("CACHE_VECTOR_SEARCH", CacheConfig.CacheConstants.CACHE_VECTOR_SEARCH);

        Map<String, Long> ttls = new HashMap<>();
        ttls.put("AI_ANSWER", CacheConfig.CacheConstants.TTL_AI_ANSWER);
        ttls.put("USER_SESSION", CacheConfig.CacheConstants.TTL_USER_SESSION);
        ttls.put("DOC_METADATA", CacheConfig.CacheConstants.TTL_DOC_METADATA);
        ttls.put("CONVERSATION_CONTEXT", CacheConfig.CacheConstants.TTL_CONVERSATION_CONTEXT);
        ttls.put("VECTOR_SEARCH", CacheConfig.CacheConstants.TTL_VECTOR_SEARCH);

        Map<String, Integer> maxEntries = new HashMap<>();
        maxEntries.put("AI_ANSWER", CacheConfig.CacheConstants.MAX_AI_ANSWER);
        maxEntries.put("USER_SESSION", CacheConfig.CacheConstants.MAX_USER_SESSION);
        maxEntries.put("DOC_METADATA", CacheConfig.CacheConstants.MAX_DOC_METADATA);
        maxEntries.put("CONVERSATION_CONTEXT", CacheConfig.CacheConstants.MAX_CONVERSATION_CONTEXT);
        maxEntries.put("VECTOR_SEARCH", CacheConfig.CacheConstants.MAX_VECTOR_SEARCH);

        config.put("constants", constants);
        config.put("ttls", ttls);
        config.put("maxEntries", maxEntries);
        config.put("cacheNames", cacheService.getCacheNames());
        return Result.success(config);
    }

    /** 缓存健康检查:逐个 getStats,能取到就认为该缓存 UP。 */
    @GetMapping("/health")
    public Result<Map<String, Object>> getCacheHealth() {
        Map<String, Object> health = new HashMap<>();

        List<String> cacheNames = cacheService.getCacheNames();
        Map<String, Boolean> cacheStatus = new HashMap<>();
        for (String cacheName : cacheNames) {
            try {
                cacheService.getStats(cacheName);
                cacheStatus.put(cacheName, true);
            } catch (Exception e) {
                cacheStatus.put(cacheName, false);
                log.warn("Cache health check failed for: {}", cacheName, e);
            }
        }

        health.put("status", "UP");
        health.put("cacheCount", cacheNames.size());
        health.put("cacheStatus", cacheStatus);
        health.put("timestamp", System.currentTimeMillis());
        return Result.success(health);
    }

    /**
     * 批量执行缓存操作,当前支持 delete、exists 两类。
     * <p>
     * 请求体形如:
     * <pre>{ "operation":"delete", "cacheName":"ai_answer", "keys":["k1","k2"] }</pre>
     * 参数缺失或不支持的 operation 一律返回 Result.error,便于调用方统一处理。
     */
    @PostMapping("/batch")
    @SuppressWarnings("unchecked")
    public Result<Map<String, Object>> batchOperation(@RequestBody Map<String, Object> request) {
        String operation = (String) request.get("operation");
        String cacheName = (String) request.get("cacheName");
        List<String> keys = (List<String>) request.get("keys");

        if (operation == null || cacheName == null) {
            return Result.error("Operation and cacheName are required");
        }

        Map<String, Object> result = new HashMap<>();
        switch (operation.toLowerCase()) {
            case "delete":
                if (keys != null && !keys.isEmpty()) {
                    cacheService.delete(cacheName, keys);
                    result.put("deletedCount", keys.size());
                }
                break;
            case "exists":
                if (keys != null && !keys.isEmpty()) {
                    Map<String, Boolean> existsMap = new HashMap<>();
                    for (String key : keys) {
                        existsMap.put(key, cacheService.exists(cacheName, key));
                    }
                    result.put("exists", existsMap);
                }
                break;
            default:
                return Result.error("Unsupported operation: " + operation);
        }

        result.put("operation", operation);
        result.put("cacheName", cacheName);
        return Result.success(result);
    }
}

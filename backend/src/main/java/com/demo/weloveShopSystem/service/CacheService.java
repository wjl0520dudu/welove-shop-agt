package com.demo.weloveShopSystem.service;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * 统一缓存服务接口。
 * 支持本地缓存和 Redis 缓存组成的多级缓存能力。
 */
public interface CacheService {

    /**
     * 设置缓存值。
     *
     * @param cacheName 缓存名称
     * @param key       缓存键
     * @param value     缓存值
     * @param ttl       过期时间
     * @param timeUnit  时间单位
     */
    void set(String cacheName, String key, Object value, long ttl, TimeUnit timeUnit);

    /**
     * 使用默认过期时间设置缓存值。
     */
    void set(String cacheName, String key, Object value);

    /**
     * 当键不存在时设置缓存值，等价于 SETNX。
     *
     * @return true 表示设置成功，false 表示键已存在
     */
    Boolean setIfAbsent(String cacheName, String key, Object value, long ttl, TimeUnit timeUnit);

    /**
     * 原子性设置新值并返回旧值，等价于 GETSET。
     */
    <T> T getAndSet(String cacheName, String key, Object value, Class<T> clazz);

    /**
     * 获取缓存值。
     */
    <T> T get(String cacheName, String key, Class<T> clazz);

    /**
     * 删除单个缓存键。
     */
    void delete(String cacheName, String key);

    /**
     * 批量删除缓存键。
     */
    void delete(String cacheName, List<String> keys);

    /**
     * 检查缓存键是否存在。
     */
    boolean exists(String cacheName, String key);

    /**
     * 获取缓存剩余过期时间，单位通常为秒。
     */
    Long getExpire(String cacheName, String key);

    /**
     * 设置缓存键的过期时间。
     */
    void expire(String cacheName, String key, long ttl, TimeUnit timeUnit);

    /**
     * 根据匹配模式获取缓存键集合。
     */
    Set<String> keys(String cacheName, String pattern);

    /**
     * 清空指定缓存。
     */
    void clear(String cacheName);

    /**
     * 获取指定缓存的统计信息。
     */
    Map<String, Object> getStats(String cacheName);

    /**
     * 获取所有缓存名称。
     */
    List<String> getCacheNames();

    /**
     * 获取指定缓存命中率，取值范围通常为 0 到 1。
     */
    double getHitRate(String cacheName);

    /**
     * 获取指定缓存条目数量。
     */
    long getSize(String cacheName);

    /**
     * 批量设置缓存值。
     */
    void setBatch(String cacheName, Map<String, Object> entries, long ttl, TimeUnit timeUnit);

    /**
     * 批量获取缓存值。
     */
    <T> Map<String, T> getBatch(String cacheName, List<String> keys, Class<T> clazz);

    /**
     * 对数值缓存执行递增。
     */
    Long increment(String cacheName, String key, long delta);

    /**
     * 对数值缓存执行递减。
     */
    Long decrement(String cacheName, String key, long delta);

    /**
     * 设置哈希表字段值。
     */
    void hset(String cacheName, String key, String field, Object value);

    /**
     * 获取哈希表字段值。
     */
    <T> T hget(String cacheName, String key, String field, Class<T> clazz);

    /**
     * 获取整个哈希表。
     */
    Map<String, Object> hgetAll(String cacheName, String key);

    /**
     * 删除哈希表中的一个或多个字段。
     */
    void hdelete(String cacheName, String key, List<String> fields);

    /**
     * 向列表左侧写入多个元素，并设置过期时间。
     */
    void lpush(String cacheName, String key, List<Object> values, long ttl, TimeUnit timeUnit);

    /**
     * 获取列表指定范围内的元素。
     */
    <T> List<T> lrange(String cacheName, String key, long start, long end, Class<T> clazz);

    /**
     * 向集合写入多个元素，并设置过期时间。
     */
    void sadd(String cacheName, String key, Set<Object> values, long ttl, TimeUnit timeUnit);

    /**
     * 获取集合中的全部元素。
     */
    <T> Set<T> smembers(String cacheName, String key, Class<T> clazz);
}

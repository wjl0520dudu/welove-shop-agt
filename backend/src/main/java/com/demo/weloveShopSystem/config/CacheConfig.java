package com.demo.weloveShopSystem.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.autoconfigure.cache.CacheAutoConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.StringRedisSerializer;

/**
 * Redis 缓存配置。
 * 提供 RedisTemplate 和 StringRedisTemplate，并排除默认缓存自动配置避免缓存管理器冲突。
 */
@Configuration
@EnableAutoConfiguration(exclude = {CacheAutoConfiguration.class})
public class CacheConfig {

    /**
     * 配置通用 RedisTemplate。
     * Key 使用字符串序列化，Value 使用 Jackson JSON 序列化，并支持 Java 8 时间类型。
     */
    @Bean
    @Primary
    public RedisTemplate<String, Object> redisTemplate(RedisConnectionFactory redisConnectionFactory) {
        RedisTemplate<String, Object> template = new RedisTemplate<>();
        template.setConnectionFactory(redisConnectionFactory);

        ObjectMapper objectMapper = new ObjectMapper();
        objectMapper.registerModule(new JavaTimeModule());
        objectMapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

        GenericJackson2JsonRedisSerializer serializer = new GenericJackson2JsonRedisSerializer(objectMapper);

        template.setKeySerializer(new StringRedisSerializer());
        template.setHashKeySerializer(new StringRedisSerializer());
        template.setValueSerializer(serializer);
        template.setHashValueSerializer(serializer);

        template.afterPropertiesSet();
        return template;
    }

    /**
     * 配置只处理字符串 key/value 的 RedisTemplate。
     */
    @Bean
    public StringRedisTemplate stringRedisTemplate(RedisConnectionFactory redisConnectionFactory) {
        StringRedisTemplate template = new StringRedisTemplate();
        template.setConnectionFactory(redisConnectionFactory);
        return template;
    }

    /**
     * 缓存名称、Key 前缀、过期时间和容量上限常量。
     */
    public static class CacheConstants {
        // 缓存名称
        public static final String CACHE_AI_ANSWER = "ai_answer";
        public static final String CACHE_USER_SESSION = "user_session";
        public static final String CACHE_DOC_METADATA = "doc_metadata";
        public static final String CACHE_CONVERSATION_CONTEXT = "conversation_context";
        public static final String CACHE_VECTOR_SEARCH = "vector_search";

        // 缓存 key 前缀
        public static final String KEY_AI_ANSWER = "ai:answer:";
        public static final String KEY_USER_SESSION = "user:session:";
        public static final String KEY_DOC_METADATA = "doc:metadata:";
        public static final String KEY_CONVERSATION_CONTEXT = "conv:ctx:";
        public static final String KEY_VECTOR_SEARCH = "vector:search:";

        // 过期时间，单位秒
        public static final long TTL_AI_ANSWER = 3600; // 1 小时
        public static final long TTL_USER_SESSION = 86400; // 24 小时
        public static final long TTL_DOC_METADATA = 300; // 5 分钟
        public static final long TTL_CONVERSATION_CONTEXT = 1800; // 30 分钟
        public static final long TTL_VECTOR_SEARCH = 600; // 10 分钟

        // 最大缓存条目数
        public static final int MAX_AI_ANSWER = 10000;
        public static final int MAX_USER_SESSION = 5000;
        public static final int MAX_DOC_METADATA = 1000;
        public static final int MAX_CONVERSATION_CONTEXT = 2000;
        public static final int MAX_VECTOR_SEARCH = 500;
    }
}

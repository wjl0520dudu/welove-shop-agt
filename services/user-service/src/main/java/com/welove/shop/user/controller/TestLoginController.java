package com.welove.shop.user.controller;

import com.welove.shop.common.core.result.Result;
import com.welove.shop.user.exception.FeatureDisabledException;
import com.welove.shop.user.exception.RequestRateLimitException;
import com.welove.shop.user.exception.UserErrorCode;
import com.welove.shop.user.service.TestLoginService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.util.Map;

/**
 * 测试登录 Controller。
 * <p>
 * 体验用户专用通道:跳过手机号+验证码,一键返回 token。
 * <p>
 * 安全设计:
 * <ul>
 *   <li>仅暴露在公开白名单 {@code /auth/test-login},无需登录</li>
 *   <li>Redis 配额:按 IP 和全局的短周期、长周期额度共同限制</li>
 *   <li>每次创建独立的 is_test 体验账号，避免不同体验者共享用户数据</li>
 *   <li>响应结构和正常 /auth/login 一致,前端无感</li>
 * </ul>
 * <p>
 * 清理任务设计见 {@code docs/plan/test-login.md} §4(本期不实现,仅文档)。
 */
@Slf4j
@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
public class TestLoginController {

    private final TestLoginService testLoginService;
    private final StringRedisTemplate redisTemplate;

    @Value("${user-service.test-login.enabled:true}")
    private boolean testLoginEnabled;

    @Value("${user-service.test-login.ip-rate-per-10-minutes:3}")
    private int ipRatePerTenMinutes;

    @Value("${user-service.test-login.ip-rate-per-day:10}")
    private int ipRatePerDay;

    @Value("${user-service.test-login.global-rate-per-hour:100}")
    private int globalRatePerHour;

    @Value("${user-service.test-login.global-rate-per-day:500}")
    private int globalRatePerDay;

    @PostMapping("/test-login")
    public Result<Map<String, Object>> testLogin(HttpServletRequest request) {
        if (!testLoginEnabled) {
            throw new FeatureDisabledException(UserErrorCode.TEST_LOGIN_DISABLED, "体验登录暂未开放");
        }

        // 1. 频控检查
        String ip = resolveClientIp(request);
        checkRateLimit(ip);

        // 2. 执行测试登录
        Map<String, Object> resp = testLoginService.testLogin();
        log.info("[test-login] 体验用户登录成功: ip={}, userId={}", ip, extractUserId(resp));
        return Result.ok(resp);
    }

    // ---------- 私有 ----------

    /** 按 IP 和全局的短周期、长周期额度共同保护账号创建写入。 */
    private void checkRateLimit(String ip) {
        checkQuota("test-login:ip:10m:" + ip, Duration.ofMinutes(10), ipRatePerTenMinutes, "IP/10m", ip);
        checkQuota("test-login:ip:day:" + ip, Duration.ofDays(1), ipRatePerDay, "IP/day", ip);
        checkQuota("test-login:global:hour", Duration.ofHours(1), globalRatePerHour, "global/hour", ip);
        checkQuota("test-login:global:day", Duration.ofDays(1), globalRatePerDay, "global/day", ip);
    }

    private void checkQuota(String key, Duration window, int limit, String dimension, String ip) {
        if (limit <= 0) {
            throw new FeatureDisabledException(UserErrorCode.TEST_LOGIN_DISABLED, "体验登录暂未开放");
        }
        Long count = redisTemplate.opsForValue().increment(key);
        if (count != null && count == 1L) {
            redisTemplate.expire(key, window);
        }
        if (count != null && count > limit) {
            log.warn("[test-login] 配额触发 dimension={}, ip={}, count={}, limit={}", dimension, ip, count, limit);
            throw new RequestRateLimitException(UserErrorCode.TEST_LOGIN_RATE_LIMIT,
                    "访问过于频繁，请稍后再试");
        }
    }

    /**
     * 取真实客户端 IP:先看 X-Forwarded-For(网关/反代),再看 X-Real-IP,最后 fallback 到 remoteAddr。
     */
    private String resolveClientIp(HttpServletRequest request) {
        String xff = request.getHeader("X-Forwarded-For");
        if (xff != null && !xff.isBlank()) {
            return xff.split(",")[0].trim();
        }
        String xri = request.getHeader("X-Real-IP");
        if (xri != null && !xri.isBlank()) {
            return xri.trim();
        }
        return request.getRemoteAddr();
    }

    @SuppressWarnings("unchecked")
    private Long extractUserId(Map<String, Object> resp) {
        Object user = resp.get("user");
        if (user instanceof Map<?, ?> userMap) {
            Object id = userMap.get("id");
            if (id instanceof Number n) return n.longValue();
        }
        return null;
    }
}

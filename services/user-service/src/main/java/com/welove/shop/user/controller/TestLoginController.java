package com.welove.shop.user.controller;

import com.welove.shop.common.core.exception.BizException;
import com.welove.shop.common.core.result.Result;
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
 *   <li>Redis 频控:同 IP 1 分钟最多 5 次,全局 1 分钟最多 100 次</li>
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

    /** 单 IP 1 分钟内最大测试登录次数。 */
    @Value("${user-service.test-login.ip-rate-per-minute:5}")
    private int ipRatePerMinute;

    /** 全局 1 分钟内最大测试登录次数(防止多 IP 协同滥用)。 */
    @Value("${user-service.test-login.global-rate-per-minute:100}")
    private int globalRatePerMinute;

    @PostMapping("/test-login")
    public Result<Map<String, Object>> testLogin(HttpServletRequest request) {
        // 1. 频控检查
        String ip = resolveClientIp(request);
        checkRateLimit(ip);

        // 2. 执行测试登录
        Map<String, Object> resp = testLoginService.testLogin();
        log.info("[test-login] 体验用户登录成功: ip={}, userId={}", ip, extractUserId(resp));
        return Result.ok(resp);
    }

    // ---------- 私有 ----------

    /**
     * 频控:同 IP 1 分钟 N 次,全局 1 分钟 M 次。
     * 超出 → 429 等价的 BizException。
     */
    private void checkRateLimit(String ip) {
        String ipKey = "test-login:ip:" + ip;
        String globalKey = "test-login:global";
        Duration window = Duration.ofMinutes(1);

        Long ipCount = redisTemplate.opsForValue().increment(ipKey);
        if (ipCount != null && ipCount == 1L) {
            redisTemplate.expire(ipKey, window);
        }
        if (ipCount != null && ipCount > ipRatePerMinute) {
            log.warn("[test-login] 频控触发 IP={}, count={}/min", ip, ipCount);
            throw new BizException(UserErrorCode.TEST_LOGIN_RATE_LIMIT,
                    "测试登录太频繁,请稍后再试(同 IP 1 分钟最多 " + ipRatePerMinute + " 次)");
        }

        Long globalCount = redisTemplate.opsForValue().increment(globalKey);
        if (globalCount != null && globalCount == 1L) {
            redisTemplate.expire(globalKey, window);
        }
        if (globalCount != null && globalCount > globalRatePerMinute) {
            log.warn("[test-login] 全局频控触发, count={}/min", globalCount);
            throw new BizException(UserErrorCode.TEST_LOGIN_RATE_LIMIT,
                    "测试登录服务繁忙,请稍后再试");
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

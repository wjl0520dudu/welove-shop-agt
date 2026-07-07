package com.demo.weloveShopSystem.controller;

import com.demo.weloveShopSystem.common.Result;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 健康检查控制器。
 * <p>
 * 供上游服务（如 ai-service、K8s liveness/readiness、Nginx 健康探测）判断本服务是否可用。
 * 走 /api/** 前缀，天然被 SecurityConfig 放行，无需 JWT。
 */
@RestController
@RequestMapping("/api/health")
@RequiredArgsConstructor
public class HealthController {

    /** 数据库连接池探针；用 SELECT 1 判断 DataSource 是否可用。 */
    private final JdbcTemplate jdbcTemplate;

    /**
     * 极简存活探针（liveness）：只要能返回 200 就代表进程活着。
     * 不查任何依赖，永远返 200，供 K8s liveness / 网关健康检查使用。
     */
    @GetMapping("/live")
    public Result<Map<String, String>> live() {
        Map<String, String> data = new LinkedHashMap<>();
        data.put("status", "alive");
        return Result.success(data);
    }

    /**
     * 就绪探针（readiness）：检查数据库是否可用。
     * 失败时业务代码仍会返回 code=200 的 Result 结构（HTTP 层 200），
     * 但 data.status 会是 "not-ready" —— 供 ai-service 或其他探测方按 data 判断。
     * <p>
     * 为什么不返 503：避免上游探测方误判超时；HTTP 层保持 200，业务状态由 data 反映。
     */
    @GetMapping("/ready")
    public Result<Map<String, Object>> ready() {
        Map<String, Object> data = new LinkedHashMap<>();
        Map<String, Object> checks = new HashMap<>();

        boolean dbOk;
        try {
            Integer result = jdbcTemplate.queryForObject("SELECT 1", Integer.class);
            dbOk = result != null && result == 1;
            checks.put("database", dbOk ? "ok" : "unexpected-result");
        } catch (Exception e) {
            dbOk = false;
            checks.put("database", "error: " + e.getClass().getSimpleName());
        }

        data.put("status", dbOk ? "ready" : "not-ready");
        data.put("checks", checks);
        return Result.success(data);
    }

    /**
     * 综合视图，人肉排查用。永远返 200。
     */
    @GetMapping
    public Result<Map<String, Object>> summary() {
        return ready();
    }
}

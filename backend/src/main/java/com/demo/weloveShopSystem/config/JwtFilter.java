package com.demo.weloveShopSystem.config;

import com.demo.weloveShopSystem.common.JwtUtil;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;
import java.util.Map;

/**
 * JWT 认证过滤器。
 * 每个请求进入 Controller 前都会尝试解析 Authorization 请求头，并写入 Spring Security 上下文。
 */
@Component
@Slf4j
@RequiredArgsConstructor
public class JwtFilter extends OncePerRequestFilter {

    /** JWT 生成、解析和校验工具。 */
    private final JwtUtil jwtUtil;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain) throws ServletException, IOException {
        // OPTIONS 预检请求直接放行，避免跨域预检被认证逻辑拦截。
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            log.debug("Skipping JWT filter for OPTIONS request: {}", request.getRequestURI());
            filterChain.doFilter(request, response);
            return;
        }

        String token = request.getHeader("Authorization");

        log.info("JWT Filter processing request: path={}, method={}, hasAuthHeader={}, token={}",
            request.getRequestURI(), request.getMethod(), token != null, token != null ? "present" : "null");

        if (token != null && token.startsWith("Bearer ")) {
            token = token.substring(7);
            log.info("Extracted token: {}", token.substring(0, Math.min(20, token.length())) + "...");

            try {
                log.info("Validating token...");
                if (jwtUtil.validateToken(token)) {
                    log.info("Token validation successful");
                    Map<String, Object> claims = jwtUtil.parseToken(token);
                    String userId = claims.get("userId").toString();
                    String role = (String) claims.get("role");

                    log.info("JWT authenticated user: userId={}, role={}, path={}",
                        userId, role, request.getRequestURI());

                    // 将 token 中的用户 ID 和角色转换为 Spring Security 认证对象。
                    UsernamePasswordAuthenticationToken authToken = new UsernamePasswordAuthenticationToken(
                            userId, null, List.of(new SimpleGrantedAuthority("ROLE_" + role.toUpperCase()))
                    );

                    SecurityContextHolder.getContext().setAuthentication(authToken);
                    log.info("Authentication set in SecurityContext for user: {}", userId);
                } else {
                    log.warn("JWT token validation failed for path: {}", request.getRequestURI());
                }
            } catch (Exception e) {
                log.error("JWT token validation failed for path {}: {}", request.getRequestURI(), e.getMessage(), e);
            }
        } else {
            log.warn("No JWT token found for path: {}", request.getRequestURI());
        }

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        log.info("Current authentication: {}", auth != null ? auth.getName() : "null");

        filterChain.doFilter(request, response);
    }
}

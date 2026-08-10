package com.welove.shop.user.config;

import com.welove.shop.common.security.config.JwtProperties;
import com.welove.shop.common.security.interceptor.JwtInterceptor;
import com.welove.shop.common.security.jwt.JwtUtil;
import org.springframework.context.annotation.Configuration;
import org.springframework.lang.NonNull;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.List;

/**
 * user-service Web 配置:注册 JWT 拦截器 + 白名单。
 * <p>
 * 白名单命中的路径无需登录即可访问,其他所有请求必须携带有效 token。
 */
@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    private final JwtUtil jwtUtil;
    private final JwtProperties jwtProperties;

    /** 免鉴权路径(网关 StripPrefix=2 后收到的路径,无 /api 前缀)。 */
    private static final List<String> WHITELIST = List.of(
            "/auth/sendCode",
            "/auth/login",
            "/auth/refresh",
            "/auth/test-login",      // 独立体验账号一键登录(频控,见 docs/plan/test-login.md)
            "/internal/**",          // 服务间 Feign 调用内核(Ph 后期与 Gateway 分层鉴权收窄)
            "/actuator/**",
            "/error"
    );

    public WebMvcConfig(JwtUtil jwtUtil, JwtProperties jwtProperties) {
        this.jwtUtil = jwtUtil;
        this.jwtProperties = jwtProperties;
    }

    @Override
    public void addInterceptors(@NonNull InterceptorRegistry registry) {
        JwtInterceptor interceptor = new JwtInterceptor(jwtUtil, jwtProperties.getHeader(), WHITELIST);
        registry.addInterceptor(interceptor)
                .addPathPatterns("/**")
                .excludePathPatterns(WHITELIST);
    }
}

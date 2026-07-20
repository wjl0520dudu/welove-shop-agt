package com.welove.shop.trade.config;

import com.welove.shop.common.security.config.JwtProperties;
import com.welove.shop.common.security.interceptor.JwtInterceptor;
import com.welove.shop.common.security.jwt.JwtUtil;
import org.springframework.context.annotation.Configuration;
import org.springframework.lang.NonNull;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.List;

/**
 * trade-service Web 配置:注册 JWT 拦截器 + 白名单。
 * <p>
 * 交易域全部需登录 —— 白名单只留 actuator + error(网关 StripPrefix=2 后收到的路径,无 /api 前缀)。
 */
@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    private final JwtUtil jwtUtil;
    private final JwtProperties jwtProperties;

    /** 免鉴权路径。 */
    private static final List<String> WHITELIST = List.of(
            "/internal/**",       // 内部统计接口(admin-bff Dashboard Feign 调)
            "/alipay/notify",     // 支付宝异步通知(公网 POST,无 JWT)
            "/alipay/return",     // 支付宝同步跳转(浏览器 GET,无 JWT)
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

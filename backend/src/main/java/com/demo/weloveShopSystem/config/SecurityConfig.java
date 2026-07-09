package com.demo.weloveShopSystem.config;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.Arrays;

/**
 * Spring Security 安全配置。
 * <p>
 * 项目采用 JWT 无状态认证,请求先经 JwtFilter 解析 Authorization 头写入 SecurityContext,
 * 再由本类根据 URL 规则决定放行或需要角色。
 * <p>
 * 权限分层:
 * <ul>
 *  <li>匿名放行:登录/短信/公告/商品和分类的只读查询/静态资源/错误页</li>
 *  <li>登录用户可访问:/api/auth/profile、/api/auth/update 等个人相关接口</li>
 *  <li>管理员专属:/api/admin/**,除 /api/admin/login,SecurityConfig + AdminInterceptor 双层校验</li>
 *  <li>其他 /api/** 业务接口要求 USER 或 ADMIN 已登录</li>
 * </ul>
 * <p>
 * welove-shop-agt 采用手机验证码登录,/api/auth/register、/api/auth/changePassword 的
 * Controller 映射默认注释,如果后续启用账号密码模式,只需去掉 AuthController 里的注释,
 * 这里的放行规则已经预留好。
 */
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    /** JWT 认证过滤器,从 Authorization 请求头解析登录用户身份。 */
    private final JwtFilter jwtFilter;

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            // 前后端分离接口不使用 CSRF Token。
            .csrf(csrf -> csrf.disable())
            // 启用跨域配置。
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))
            .authorizeHttpRequests(auth -> auth
                // ---------- 1. 预检 & 静态资源 & 错误页 ----------
                .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                .requestMatchers("/product-images/**").permitAll()
                .requestMatchers("/error").permitAll()
                .requestMatchers("/api/health/**").permitAll()

                // ---------- 2. 前台匿名接口 ----------
                // 手机验证码登录、短信、刷新 token
                .requestMatchers("/api/auth/sendCode").permitAll()
                .requestMatchers("/api/auth/login").permitAll()
                .requestMatchers("/api/auth/refresh").permitAll()
                // 账号密码注册/改密预留放行(Controller 层默认注释,不生效也不报错)
                .requestMatchers("/api/auth/register").permitAll()
                // 公告(前台)
                .requestMatchers(HttpMethod.GET, "/api/notice/latest").permitAll()
                // 分类与商品的只读查询
                .requestMatchers(HttpMethod.GET, "/api/category/list").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/category/*").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/product/list").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/product/search").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/product/hot").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/product/*").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/product/*/skus").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/product/*/reviews").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/product/*/faqs").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/product/*/images").permitAll()

                // ---------- 3. 已登录用户可访问 ----------
                .requestMatchers("/api/auth/profile").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/auth/update").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/auth/changePassword").hasAnyRole("USER", "ADMIN")

                // ---------- 4. 后台管理接口 ----------
                // 管理员登录本身要匿名
                .requestMatchers("/api/admin/login").permitAll()
                // 其余全部要求 ADMIN 角色;AdminInterceptor 会再校验一次 token 里的 role
                .requestMatchers("/api/admin/**").hasRole("ADMIN")
                // AdminChat 挂在 /api/admin-chat 不在 /api/admin/** 之下,单独收口
                .requestMatchers("/api/admin-chat/**").hasRole("ADMIN")
                // 缓存管理接口只给 ADMIN,不放在 admin 路径下所以单独收口
                .requestMatchers("/api/cache/**").hasRole("ADMIN")

                // ---------- 5. 其他业务接口:登录即可 ----------
                .requestMatchers("/api/chat/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/knowledge/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/category/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/product/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/recommend/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/address/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/order/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/cart/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/agent/**").hasAnyRole("USER", "ADMIN")
                .requestMatchers("/api/notice/**").hasAnyRole("USER", "ADMIN")

                // ---------- 6. 兜底 ----------
                .anyRequest().authenticated()
            )
            // 在 UsernamePasswordAuthenticationFilter 之前挂 JWT 解析
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class)
            .formLogin(form -> form.disable())
            .httpBasic(httpBasic -> httpBasic.disable());

        // JWT 无状态,不创建 HTTP Session
        http.sessionManagement(session -> session
            .sessionCreationPolicy(SessionCreationPolicy.STATELESS)
        );

        return http.build();
    }

    /** CORS:允许所有 Origin 携带凭证访问 /api/**,并暴露 Authorization 让前端读到刷新后的 token。 */
    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration configuration = new CorsConfiguration();
        configuration.setAllowedOriginPatterns(Arrays.asList("*"));
        configuration.setAllowedMethods(Arrays.asList("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        configuration.setAllowedHeaders(Arrays.asList("*"));
        configuration.setAllowCredentials(true);
        configuration.setExposedHeaders(Arrays.asList("Authorization"));

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/api/**", configuration);
        return source;
    }
}

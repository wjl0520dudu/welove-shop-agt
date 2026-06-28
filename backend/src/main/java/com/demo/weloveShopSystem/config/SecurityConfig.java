package com.demo.weloveShopSystem.config;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
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
 * 负责接口放行规则、角色授权、CORS、JWT 过滤器和无状态会话策略。
 */
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    /** JWT 认证过滤器，用于从 Authorization 请求头中解析登录用户。 */
    private final JwtFilter jwtFilter;

    /**
     * 配置安全过滤链。
     */
    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            // 前后端分离接口不使用 CSRF Token。
            .csrf(csrf -> csrf.disable())
            // 启用跨域配置。
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))
            // 配置接口访问权限。
            .authorizeHttpRequests(auth -> auth
                // OPTIONS 预检请求直接放行。
                .requestMatchers(org.springframework.http.HttpMethod.OPTIONS, "/**").permitAll()
                // 用户登录注册相关接口允许匿名访问。
                .requestMatchers("/api/auth/sendCode").permitAll()
                .requestMatchers("/api/auth/register").permitAll()
                .requestMatchers("/api/auth/login").permitAll()
                .requestMatchers("/api/auth/refresh").permitAll().requestMatchers("/api/**").permitAll()
                // 其余接口只要求已登录。待开发
                .anyRequest().authenticated()
            )
            // 在用户名密码认证过滤器之前执行 JWT 解析。
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class)
            // 禁用 Spring Security 默认表单登录。
            .formLogin(form -> form.disable())
            // 禁用 HTTP Basic 认证。
            .httpBasic(httpBasic -> httpBasic.disable());

        // 使用 JWT 无状态认证，不在服务端创建 HTTP Session。
        http.sessionManagement(session -> session
            .sessionCreationPolicy(SessionCreationPolicy.STATELESS)
        );

        return http.build();
    }

    /**
     * 配置跨域规则。
     */
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

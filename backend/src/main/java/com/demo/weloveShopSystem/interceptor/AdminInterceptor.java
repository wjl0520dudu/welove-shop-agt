package com.demo.weloveShopSystem.interceptor;

import com.demo.weloveShopSystem.common.ErrorCode;
import com.demo.weloveShopSystem.common.JwtUtil;
import com.demo.weloveShopSystem.exception.BusinessException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.Map;

/**
 * 管理员接口拦截器。
 * <p>
 * Spring Security 已经通过 hasRole("ADMIN") 做过一层授权,这里再补一层显式校验,
 * 让 /api/admin/** 的越权访问在进入 Controller 之前就抛出统一业务异常,便于:
 *  1) 前端拿到统一 ErrorCode.INVALID_TOKEN,而不是 Security 默认的 403 空响应;
 *  2) 后续加管理员会话记录、审计埋点等横切逻辑时,拦截器是最合适的挂载点。
 */
@Component
@RequiredArgsConstructor
public class AdminInterceptor implements HandlerInterceptor {

    private final JwtUtil jwtUtil;

    // Spring 已在接口层声明了 null-safety 契约,Eclipse JDT 的空值校验器认的是
    // 它自己的 org.eclipse.jdt.annotation 注解,项目里没有该依赖,直接压制该
    // 告警,避免为一个纯 IDE 警告引入一整个 JDT annotation 依赖。
    @SuppressWarnings("null")
    @Override
    public boolean preHandle(HttpServletRequest request,
                             HttpServletResponse response,
                             Object handler) throws Exception {
        String token = request.getHeader("Authorization");

        if (token == null || !token.startsWith("Bearer ")) {
            throw new BusinessException(ErrorCode.INVALID_TOKEN, "无权访问:缺少有效的管理员 token");
        }

        token = token.substring(7);

        try {
            if (!jwtUtil.validateToken(token)) {
                throw new BusinessException(ErrorCode.INVALID_TOKEN, "无权访问:无效的 token");
            }
            Map<String, Object> claims = jwtUtil.parseToken(token);
            String role = (String) claims.get("role");
            if (!"ADMIN".equals(role)) {
                throw new BusinessException(ErrorCode.INVALID_TOKEN, "无权访问:非管理员请求");
            }
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new BusinessException(ErrorCode.INVALID_TOKEN, "无权访问:token 验证失败");
        }
        return true;
    }
}

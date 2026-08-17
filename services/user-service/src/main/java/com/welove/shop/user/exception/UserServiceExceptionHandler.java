package com.welove.shop.user.exception;

import com.welove.shop.common.core.result.Result;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * user-service 需要保留 HTTP 语义的异常。
 *
 * <p>通用 {@code BizException} 仍遵守项目的 Result 错误码约定；只有公共能力开关和
 * 写入型接口限流需要让浏览器、网关和监控识别为 403/429。</p>
 */
@Slf4j
@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice
public class UserServiceExceptionHandler {

    @ExceptionHandler(RequestRateLimitException.class)
    public ResponseEntity<Result<Void>> handleRateLimit(RequestRateLimitException ex,
                                                         HttpServletRequest request) {
        log.warn("[RateLimit] {} {} - code={}, msg={}",
                request.getMethod(), request.getRequestURI(), ex.getCode(), ex.getMessage());
        return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                .header(HttpHeaders.RETRY_AFTER, "60")
                .body(Result.fail(ex.getCode(), ex.getMessage()));
    }

    @ExceptionHandler(FeatureDisabledException.class)
    public ResponseEntity<Result<Void>> handleFeatureDisabled(FeatureDisabledException ex,
                                                              HttpServletRequest request) {
        log.info("[FeatureDisabled] {} {} - code={}, msg={}",
                request.getMethod(), request.getRequestURI(), ex.getCode(), ex.getMessage());
        return ResponseEntity.status(HttpStatus.FORBIDDEN)
                .body(Result.fail(ex.getCode(), ex.getMessage()));
    }
}

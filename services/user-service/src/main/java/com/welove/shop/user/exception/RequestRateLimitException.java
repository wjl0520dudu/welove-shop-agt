package com.welove.shop.user.exception;

import com.welove.shop.common.core.exception.BizException;

/**
 * 写入型公开接口的业务配额耗尽。
 *
 * <p>由 {@code UserServiceExceptionHandler} 转换为 HTTP 429。</p>
 */
public class RequestRateLimitException extends BizException {

    public RequestRateLimitException(int code, String message) {
        super(code, message);
    }
}

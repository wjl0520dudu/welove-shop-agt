package com.demo.weloveShopSystem.exception;

import com.demo.weloveShopSystem.common.ErrorCode;
import lombok.Getter;

/**
 * 业务异常。
 * 用于主动抛出带业务错误码的异常，由全局异常处理器统一转换为接口响应。
 */
@Getter
public class BusinessException extends RuntimeException {
    /** 业务错误码。 */
    private final int code;
    /** 业务错误信息。 */
    private final String message;

    /**
     * 根据统一错误码创建业务异常。
     */
    public BusinessException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.code = errorCode.getCode();
        this.message = errorCode.getMessage();
    }

    /**
     * 根据统一错误码和自定义错误信息创建业务异常。
     */
    public BusinessException(ErrorCode errorCode, String message) {
        super(message);
        this.code = errorCode.getCode();
        this.message = message;
    }
}

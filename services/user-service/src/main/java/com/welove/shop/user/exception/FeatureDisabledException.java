package com.welove.shop.user.exception;

import com.welove.shop.common.core.exception.BizException;

/**
 * 由部署配置关闭的公开能力。
 *
 * <p>由 {@code UserServiceExceptionHandler} 转换为 HTTP 403，避免仅靠前端禁用按钮。</p>
 */
public class FeatureDisabledException extends BizException {

    public FeatureDisabledException(int code, String message) {
        super(code, message);
    }
}

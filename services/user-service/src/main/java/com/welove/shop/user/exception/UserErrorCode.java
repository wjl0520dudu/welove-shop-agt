package com.welove.shop.user.exception;

/**
 * user-service 域业务错误码。
 * <p>
 * 编码规则:20xxx = 用户域(与 common-core 的 1xxxx 通用错误码不冲突)。
 */
public final class UserErrorCode {

    private UserErrorCode() {
    }

    // ---------- 参数校验 ----------
    public static final int INVALID_PHONE_FORMAT = 20001;
    public static final int VERIFICATION_CODE_REQUIRED = 20002;
    public static final int VERIFICATION_CODE_EXPIRED = 20003;
    public static final int INVALID_VERIFICATION_CODE = 20004;
    public static final int PASSWORD_TOO_SHORT = 20005;
    public static final int USERNAME_SENSITIVE = 20006;

    // ---------- 业务规则 ----------
    public static final int USER_NOT_FOUND = 20101;
    public static final int PHONE_ALREADY_REGISTERED = 20102;
    public static final int ACCOUNT_DISABLED = 20103;
    public static final int OLD_PASSWORD_WRONG = 20104;
    public static final int INVALID_TOKEN = 20105;

    // ---------- 测试登录 ----------
    public static final int TEST_LOGIN_RATE_LIMIT = 20201;
    public static final int TEST_LOGIN_DISABLED = 20202;

    // ---------- 演示环境功能开关 ----------
    public static final int SMS_LOGIN_DISABLED = 20301;
}

package com.demo.weloveShopSystem.common;

import lombok.Getter;

/**
 * 统一错误码定义。
 */
@Getter
public enum ErrorCode {
    /** 请求成功。 */
    SUCCESS(200, "Success"),
    /** 系统内部错误。 */
    SYSTEM_ERROR(500, "System Error"),
    /** 请求参数非法。 */
    INVALID_PARAMS(400, "Invalid Parameters"),

    // Auth related
    /** 手机号格式错误。 */
    INVALID_PHONE_FORMAT(4001, "手机号格式错误，请输入 11 位有效手机号"),
    /** 验证码不能为空。 */
    VERIFICATION_CODE_REQUIRED(4002, "验证码不能为空"),
    /** 验证码已过期或未发送。 */
    VERIFICATION_CODE_EXPIRED(4003, "验证码已过期或未发送"),
    /** 验证码错误。 */
    INVALID_VERIFICATION_CODE(4004, "验证码错误"),
    /** 手机号已注册。 */
    PHONE_ALREADY_REGISTERED(4005, "该手机号已注册"),
    /** 用户名包含敏感词。 */
    USERNAME_SENSITIVE(4006, "用户名包含敏感词"),
    /** 用户不存在。 */
    USER_NOT_FOUND(4007, "用户不存在，请先注册"),
    /** 密码错误。 */
    INVALID_PASSWORD(4008, "密码错误"),
    /** 密码长度不足。 */
    PASSWORD_TOO_SHORT(4009, "密码长度不能少于 6 位"),
    /** Token 无效。 */
    INVALID_TOKEN(4010, "无效的 token"),
    /** 原密码错误。 */
    OLD_PASSWORD_WRONG(4011, "原密码错误");

    /** 业务错误码。 */
    private final int code;
    /** 展示给调用方的错误信息。 */
    private final String message;

    ErrorCode(int code, String message) {
        this.code = code;
        this.message = message;
    }
}

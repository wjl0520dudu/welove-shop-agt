package com.demo.weloveShopSystem.dto;

import lombok.Data;

/**
 * 用户登录请求参数。
 */
@Data
public class LoginRequest {
    /** 登录手机号。 */
    private String phone;

    /** 短信验证码。 */
    private String code;

    /** 登录密码，兼容旧密码登录请求。 */
    private String password;
}
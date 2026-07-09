package com.demo.weloveShopSystem.dto;

import lombok.Data;

/**
 * 用户注册请求参数。
 * <p>
 * 手机验证码登录项目默认不启用注册接口,此 DTO 保留供后续启用账号密码注册流程时使用。
 */
@Data
public class RegisterRequest {
    /** 注册手机号。 */
    private String phone;
    /** 短信验证码。 */
    private String code;
    /** 登录密码。 */
    private String password;
    /** 用户名;为空时后端会生成默认用户名。 */
    private String username;
}

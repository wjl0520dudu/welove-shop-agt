package com.demo.weloveShopSystem.dto;

import lombok.Data;

/**
 * 修改密码请求参数。
 * <p>
 * 手机验证码登录项目默认不启用改密接口,此 DTO 保留供后续启用账号密码登录流程时使用。
 */
@Data
public class ChangePasswordRequest {
    /** 用户当前旧密码。 */
    private String oldPassword;
    /** 用户准备设置的新密码。 */
    private String newPassword;
}

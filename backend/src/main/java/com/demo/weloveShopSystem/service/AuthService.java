package com.demo.weloveShopSystem.service;

import java.util.Map;

/**
 * 用户认证和资料服务接口。
 */
public interface AuthService {
    /**
     * 发送短信验证码。
     *
     * @param phone 手机号
     */
    void sendSmsCode(String phone);

    /**
     * 验证码登录；手机号不存在时自动注册，成功后返回 token 和用户信息。
     *
     * @param phone 手机号
     * @param code 短信验证码
     * @return 登录结果
     */
    Map<String, Object> login(String phone, String code);
}
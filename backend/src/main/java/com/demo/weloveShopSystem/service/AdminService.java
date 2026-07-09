package com.demo.weloveShopSystem.service;

import java.util.Map;

/**
 * 管理员认证服务接口。
 * <p>
 * 与 AuthService 分开:后台管理员单独一张表、走用户名密码登录,
 * 与 C 端手机验证码登录的鉴权链路不共享,避免两个业务耦合在一个 Service 里。
 */
public interface AdminService {
    /**
     * 管理员登录,校验通过后返回 access token 与管理员信息。
     *
     * @param username 管理员用户名
     * @param password 明文密码(内部走 BCrypt 比对)
     * @return 包含 accessToken / refreshToken / tokenType / admin 的 map
     */
    Map<String, Object> login(String username, String password);
}

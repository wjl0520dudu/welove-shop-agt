package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.dto.UpdateUserRequest;
import com.demo.weloveShopSystem.entity.User;

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
     * 验证码登录;手机号不存在时自动注册,成功后返回 token 和用户信息。
     *
     * @param phone 手机号
     * @param code  短信验证码
     * @return 登录结果
     */
    Map<String, Object> login(String phone, String code);

    /** 根据用户 ID 查询用户信息。 */
    User getUserById(Long userId);

    /** 根据刷新 token 换取新的访问 token。 */
    Map<String, Object> refreshToken(String token);

    /**
     * 更新用户资料;字段以非 null / 非空为准,允许调用方只提交需要修改的字段。
     *
     * @param request 更新请求,userId 由 Controller 从 JWT 中解析后写入
     * @return 更新后的用户实体
     */
    User updateUserInfo(UpdateUserRequest request);

    /**
     * 使用手机号、验证码、密码和用户名注册用户。
     * <p>
     * 手机验证码登录项目默认不启用;方法保留是为了保留账号密码注册流程的扩展能力,
     * 后续启用只需在 Controller 层放开对应映射即可。
     *
     * @param phone    手机号
     * @param code     短信验证码
     * @param password 登录密码(明文,内部会做 BCrypt 加密)
     * @param username 用户名,为空时后端会生成默认用户名
     * @return 注册后的 token 和用户信息
     */
    Map<String, Object> register(String phone, String code, String password, String username);

    /**
     * 修改用户密码。
     * <p>
     * 手机验证码登录项目默认不启用;当账号存在真正的登录密码时才有意义。
     *
     * @param userId      用户 ID
     * @param oldPassword 原密码(明文)
     * @param newPassword 新密码(明文,长度需 >= 6)
     */
    void changePassword(Long userId, String oldPassword, String newPassword);
}

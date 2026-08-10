package com.welove.shop.user.service;

import java.util.Map;

/**
 * 测试登录服务。
 * <p>
 * 为体验用户提供的"一键登录"通道,跳过手机号+验证码环节。
 * 调用方:
 * <ul>
 *   <li>{@link com.welove.shop.user.controller.TestLoginController#testLogin}</li>
 * </ul>
 * <p>
 * 设计:
 * <ul>
 *   <li>每次体验登录创建独立测试账号,避免不同体验者共享聊天、收藏和订单数据</li>
 *   <li>更新 last_login_at 供后续清理任务使用</li>
 *   <li>频控由 Controller 层用 Redis 实现,见 TestLoginController</li>
 * </ul>
 * <p>
 * 账号清理策略见 {@code docs/plan/test-login.md} §4。
 */
public interface TestLoginService {

    /**
     * 执行测试登录:创建独立测试账号,记录最后登录时间并颁发 token。
     *
     * @return 与普通 login 相同的响应结构({@code token, refreshToken, user, tokenType})
     */
    Map<String, Object> testLogin();
}

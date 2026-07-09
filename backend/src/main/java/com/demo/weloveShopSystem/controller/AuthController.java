package com.demo.weloveShopSystem.controller;

import com.demo.weloveShopSystem.common.Result;
// import com.demo.weloveShopSystem.dto.ChangePasswordRequest;
import com.demo.weloveShopSystem.dto.LoginRequest;
// import com.demo.weloveShopSystem.dto.RegisterRequest;
import com.demo.weloveShopSystem.dto.UpdateUserRequest;
import com.demo.weloveShopSystem.entity.User;
import com.demo.weloveShopSystem.service.AuthService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 用户认证控制器。
 * <p>
 * welove-shop-agt 定位为手机验证码登录,仅暴露 /sendCode + /login + /refresh + /profile + /update 这 5 个接口;
 * /register、/changePassword 的服务层实现已就绪,但接口层默认不放开,若后续切换为账号密码模式再放开即可。
 */
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    /**
     * 发送短信验证码。
     */
    @PostMapping("/sendCode")
    public Result<String> sendCode(@RequestParam String phone) {
        authService.sendSmsCode(phone);
        return Result.success("Verification code sent");
    }

    /**
     * 手机号验证码登录,未注册手机号会自动创建账号。
     */
    @PostMapping("/login")
    public Result<Map<String, Object>> login(@RequestBody LoginRequest request) {
        Map<String, Object> result = authService.login(request.getPhone(), request.getCode());
        return Result.success(result);
    }

    /** 刷新访问 token。 */
    @PostMapping("/refresh")
    public Result<Map<String, Object>> refreshToken(@RequestHeader("Authorization") String token) {
        Map<String, Object> result = authService.refreshToken(token);
        return Result.success(result);
    }

    /** 获取当前用户资料。 */
    @GetMapping("/profile")
    public Result<User> getProfile() {
        Long userId = Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
        User user = authService.getUserById(userId);
        return Result.success(user);
    }

    /**
     * 更新当前用户资料。
     * <p>
     * userId 从 SecurityContext 中的 JWT 主体解析,忽略请求体里客户端传入的 userId,防止越权修改他人资料。
     */
    @PostMapping("/update")
    public Result<User> updateUserInfo(@RequestBody UpdateUserRequest request) {
        Long userId = Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
        request.setUserId(userId);
        User user = authService.updateUserInfo(request);
        return Result.success(user);
    }

    /*
     * ---------- 以下账号密码相关接口在手机验证码登录项目中默认关闭 ----------
     * 服务层 register / changePassword 方法已实现,启用只需去掉下方注释和顶部 import 注释即可。
     *
     * @PostMapping("/register")
     * public Result<Map<String, Object>> register(@RequestBody RegisterRequest request) {
     *     Map<String, Object> result = authService.register(
     *             request.getPhone(),
     *             request.getCode(),
     *             request.getPassword(),
     *             request.getUsername());
     *     return Result.success(result);
     * }
     *
     * @PostMapping("/changePassword")
     * public Result<String> changePassword(@RequestBody ChangePasswordRequest request) {
     *     Long userId = Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
     *     authService.changePassword(userId, request.getOldPassword(), request.getNewPassword());
     *     return Result.success("密码修改成功");
     * }
     */
}

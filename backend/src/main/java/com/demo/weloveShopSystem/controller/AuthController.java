package com.demo.weloveShopSystem.controller;

import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.dto.LoginRequest;
import com.demo.weloveShopSystem.entity.User;
import com.demo.weloveShopSystem.service.AuthService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 用户认证控制器。
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
     * 手机号验证码登录，未注册手机号会自动创建账号。
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
}
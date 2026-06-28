package com.demo.weloveShopSystem.controller;

import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.dto.LoginRequest;
import com.demo.weloveShopSystem.service.AuthService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

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
}
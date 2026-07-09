package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.weloveShopSystem.common.ErrorCode;
import com.demo.weloveShopSystem.common.JwtUtil;
import com.demo.weloveShopSystem.entity.Admin;
import com.demo.weloveShopSystem.exception.BusinessException;
import com.demo.weloveShopSystem.mapper.AdminMapper;
import com.demo.weloveShopSystem.service.AdminService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;

/**
 * 管理员认证服务实现。
 * <p>
 * 密码校验策略:优先按 BCrypt 密文比对;若失败则尝试历史明文比对,匹配后自动
 * 升级为 BCrypt 存储。这样既能支持新账号 BCrypt 落库,又能兼容早期用明文
 * 初始化的账号,不需要一次性 DBA 迁移。
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class AdminServiceImpl implements AdminService {

    private final AdminMapper adminMapper;
    private final JwtUtil jwtUtil;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Override
    public Map<String, Object> login(String username, String password) {
        Admin admin = adminMapper.selectOne(new LambdaQueryWrapper<Admin>()
                .eq(Admin::getUsername, username));
        if (admin == null) {
            throw new BusinessException(ErrorCode.INVALID_PASSWORD, "用户名或密码错误");
        }

        boolean matched;
        if (passwordEncoder.matches(password, admin.getPassword())) {
            matched = true;
        } else if (password != null && password.equals(admin.getPassword())) {
            // 兼容早期明文存储:验证通过后立即升级为 BCrypt。
            admin.setPassword(passwordEncoder.encode(password));
            adminMapper.updateById(admin);
            log.info("Admin password migrated to BCrypt: id={}, username={}", admin.getId(), username);
            matched = true;
        } else {
            matched = false;
        }
        if (!matched) {
            throw new BusinessException(ErrorCode.INVALID_PASSWORD, "用户名或密码错误");
        }

        Map<String, Object> claims = new HashMap<>();
        claims.put("userId", admin.getId());
        claims.put("username", admin.getUsername());
        claims.put("role", "ADMIN");

        String accessToken = jwtUtil.generateToken(admin.getId().toString(), claims);
        String refreshToken = jwtUtil.generateRefreshToken(admin.getId().toString());

        Map<String, Object> result = new HashMap<>();
        result.put("accessToken", accessToken);
        result.put("refreshToken", refreshToken);
        result.put("tokenType", "Bearer");
        result.put("admin", admin);
        return result;
    }
}

package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.weloveShopSystem.common.ErrorCode;
import com.demo.weloveShopSystem.common.JwtUtil;
import com.demo.weloveShopSystem.common.SensitiveWordUtil;
import com.demo.weloveShopSystem.dto.UpdateUserRequest;
import com.demo.weloveShopSystem.entity.User;
import com.demo.weloveShopSystem.exception.BusinessException;
import com.demo.weloveShopSystem.mapper.UserMapper;
import com.demo.weloveShopSystem.service.AuthService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

@Service
@Slf4j
@RequiredArgsConstructor
public class AuthServiceImpl implements AuthService {

    private static final String SMS_CODE_PREFIX = "sms:code:";
    private static final long SMS_CODE_EXPIRE = 5;

    private final UserMapper userMapper;
    private final StringRedisTemplate redisTemplate;
    private final JwtUtil jwtUtil;
    private final SensitiveWordUtil sensitiveWordUtil;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Override
    public void sendSmsCode(String phone) {
        if (!isValidPhone(phone)) {
            throw new BusinessException(ErrorCode.INVALID_PHONE_FORMAT);
        }

        String code = String.valueOf(new Random().nextInt(900000) + 100000);
        log.info("【模拟短信】验证码已发送至 {}: {}", phone, code);
        redisTemplate.opsForValue().set(SMS_CODE_PREFIX + phone, code, SMS_CODE_EXPIRE, TimeUnit.MINUTES);
    }

    @Override
    public Map<String, Object> login(String phone, String code) {
        if (!isValidPhone(phone)) {
            log.warn("Login attempt with invalid phone format: {}", phone);
            throw new BusinessException(ErrorCode.INVALID_PHONE_FORMAT);
        }
        if (!StringUtils.hasText(code)) {
            throw new BusinessException(ErrorCode.VERIFICATION_CODE_REQUIRED);
        }

        String redisKey = SMS_CODE_PREFIX + phone;
        String cachedCode = redisTemplate.opsForValue().get(redisKey);
        if (!StringUtils.hasText(cachedCode)) {
            throw new BusinessException(ErrorCode.VERIFICATION_CODE_EXPIRED);
        }
        if (!cachedCode.equals(code)) {
            throw new BusinessException(ErrorCode.INVALID_VERIFICATION_CODE);
        }

        User user = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getPhone, phone));
        if (user == null) {
            user = createUser(phone);
            log.info("User auto registered by sms login: phone={}, userId={}", phone, user.getId());
        } else if (user.getStatus() != null && user.getStatus() == 0) {
            throw new BusinessException(ErrorCode.INVALID_PARAMS, "账号已被禁用");
        }

        redisTemplate.delete(redisKey);
        log.info("User sms login successful: phone={}, userId={}", phone, user.getId());
        return generateTokenResponse(user);
    }

    @Override
    public User getUserById(Long userId) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new BusinessException(ErrorCode.USER_NOT_FOUND);
        }
        return user;
    }

    @Override
    public Map<String, Object> refreshToken(String token) {
        if (token.startsWith("Bearer ")) {
            token = token.substring(7);
        }

        try {
            if (jwtUtil.validateToken(token)) {
                String userIdStr = jwtUtil.getSubject(token);
                Long userId = Long.parseLong(userIdStr);
                User user = userMapper.selectById(userId);
                if (user != null) {
                    return generateTokenResponse(user);
                }
            }
        } catch (Exception e) {
            log.error("Token refresh failed: {}", e.getMessage());
        }
        throw new BusinessException(ErrorCode.INVALID_TOKEN);
    }

    @Override
    public User updateUserInfo(UpdateUserRequest request) {
        User user = userMapper.selectById(request.getUserId());
        if (user == null) {
            throw new BusinessException(ErrorCode.USER_NOT_FOUND);
        }
        // 只更新明确传入的字段,避免覆盖已有数据。
        if (StringUtils.hasText(request.getUsername())) {
            if (sensitiveWordUtil.contains(request.getUsername())) {
                throw new BusinessException(ErrorCode.USERNAME_SENSITIVE);
            }
            user.setUsername(request.getUsername());
        }
        if (StringUtils.hasText(request.getPassword())) {
            user.setPassword(passwordEncoder.encode(request.getPassword()));
        }
        if (request.getAvatarUrl() != null) {
            user.setAvatarUrl(request.getAvatarUrl());
        }
        if (request.getGender() != null) {
            user.setGender(request.getGender());
        }
        if (request.getAgeRange() != null) {
            user.setAgeRange(request.getAgeRange());
        }
        if (request.getSkinType() != null) {
            user.setSkinType(request.getSkinType());
        }
        if (request.getPreferenceTags() != null) {
            user.setPreferenceTags(request.getPreferenceTags());
        }
        user.setUpdateTime(LocalDateTime.now());
        userMapper.updateById(user);
        return user;
    }

    @Override
    public Map<String, Object> register(String phone, String code, String password, String username) {
        // 1. 基础校验
        if (!isValidPhone(phone)) {
            throw new BusinessException(ErrorCode.INVALID_PHONE_FORMAT);
        }
        if (!StringUtils.hasText(code)) {
            throw new BusinessException(ErrorCode.VERIFICATION_CODE_REQUIRED);
        }
        if (!StringUtils.hasText(password) || password.length() < 6) {
            throw new BusinessException(ErrorCode.PASSWORD_TOO_SHORT);
        }

        // 2. 校验验证码
        String cachedCode = redisTemplate.opsForValue().get(SMS_CODE_PREFIX + phone);
        if (cachedCode == null) {
            throw new BusinessException(ErrorCode.VERIFICATION_CODE_EXPIRED);
        }
        if (!cachedCode.equals(code)) {
            throw new BusinessException(ErrorCode.INVALID_VERIFICATION_CODE);
        }

        // 3. 检查手机号是否已存在
        User existingUser = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getPhone, phone));
        if (existingUser != null) {
            throw new BusinessException(ErrorCode.PHONE_ALREADY_REGISTERED);
        }

        // 4. 用户名兜底 + 敏感词校验
        String finalUsername = StringUtils.hasText(username) ? username : "User_" + phone.substring(7);
        if (sensitiveWordUtil.contains(finalUsername)) {
            throw new BusinessException(ErrorCode.USERNAME_SENSITIVE);
        }

        // 5. 创建用户
        User user = new User();
        user.setPhone(phone);
        user.setPassword(passwordEncoder.encode(password));
        user.setUsername(finalUsername);
        user.setStatus(1);
        user.setCreateTime(LocalDateTime.now());
        user.setUpdateTime(LocalDateTime.now());
        userMapper.insert(user);

        // 6. 注册成功后清理验证码
        redisTemplate.delete(SMS_CODE_PREFIX + phone);

        return generateTokenResponse(user);
    }

    @Override
    public void changePassword(Long userId, String oldPassword, String newPassword) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new BusinessException(ErrorCode.USER_NOT_FOUND);
        }
        if (!StringUtils.hasText(oldPassword) || !passwordEncoder.matches(oldPassword, user.getPassword())) {
            throw new BusinessException(ErrorCode.OLD_PASSWORD_WRONG);
        }
        if (!StringUtils.hasText(newPassword) || newPassword.length() < 6) {
            throw new BusinessException(ErrorCode.PASSWORD_TOO_SHORT);
        }
        user.setPassword(passwordEncoder.encode(newPassword));
        user.setUpdateTime(LocalDateTime.now());
        userMapper.updateById(user);
    }

    private User createUser(String phone) {
        User user = new User();
        user.setPhone(phone);
        user.setUsername("用户" + phone.substring(phone.length() - 4));
        user.setPassword(passwordEncoder.encode("sms-login-" + phone + "-" + System.currentTimeMillis()));
        user.setGender(0);
        user.setStatus(1);
        user.setCreateTime(LocalDateTime.now());
        user.setUpdateTime(LocalDateTime.now());
        userMapper.insert(user);
        return user;
    }

    private boolean isValidPhone(String phone) {
        return phone != null && Pattern.matches("^1[3-9]\\d{9}$", phone);
    }

    private Map<String, Object> generateTokenResponse(User user) {
        Map<String, Object> claims = new HashMap<>();
        claims.put("userId", user.getId());
        claims.put("phone", user.getPhone());
        claims.put("username", user.getUsername());
        claims.put("role", "USER");

        String accessToken = jwtUtil.generateToken(user.getId().toString(), claims);
        String refreshToken = jwtUtil.generateRefreshToken(user.getId().toString());

        Map<String, Object> response = new HashMap<>();
        response.put("user", user);
        response.put("token", accessToken);
        response.put("refreshToken", refreshToken);
        response.put("tokenType", "Bearer");
        return response;
    }

}

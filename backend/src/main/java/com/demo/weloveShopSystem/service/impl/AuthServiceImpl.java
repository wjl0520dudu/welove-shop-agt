package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.weloveShopSystem.common.ErrorCode;
import com.demo.weloveShopSystem.common.JwtUtil;
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
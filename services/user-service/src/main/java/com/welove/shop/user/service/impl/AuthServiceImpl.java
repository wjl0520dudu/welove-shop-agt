package com.welove.shop.user.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.welove.shop.common.core.exception.BizException;
import com.welove.shop.common.core.exception.ErrorCode;
import com.welove.shop.common.security.jwt.JwtUtil;
import com.welove.shop.user.dto.UpdateUserRequest;
import com.welove.shop.user.entity.User;
import com.welove.shop.user.exception.FeatureDisabledException;
import com.welove.shop.user.exception.UserErrorCode;
import com.welove.shop.user.mapper.UserMapper;
import com.welove.shop.user.service.AuthService;
import com.welove.shop.user.util.SensitiveWordUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

/**
 * 用户认证与资料服务实现。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AuthServiceImpl implements AuthService {

    private static final String SMS_CODE_PREFIX = "sms:code:";
    private static final Pattern PHONE_PATTERN = Pattern.compile("^1[3-9]\\d{9}$");

    private final UserMapper userMapper;
    private final StringRedisTemplate redisTemplate;
    private final JwtUtil jwtUtil;
    private final PasswordEncoder passwordEncoder;
    private final SensitiveWordUtil sensitiveWordUtil;

    @Value("${user-service.sms.mock:true}")
    private boolean smsMock;

    @Value("${user-service.sms.code-ttl-seconds:300}")
    private long codeTtlSeconds;

    /** 演示环境关闭手机号登录，避免 mock 短信接口成为额外公开注册入口。 */
    @Value("${user-service.sms-login.enabled:false}")
    private boolean smsLoginEnabled;

    // ---------- 短信验证码 ----------

    @Override
    public void sendSmsCode(String phone) {
        ensureSmsLoginEnabled();
        if (!isValidPhone(phone)) {
            throw new BizException(UserErrorCode.INVALID_PHONE_FORMAT, "手机号格式错误");
        }
        String code = String.valueOf(new Random().nextInt(900_000) + 100_000);
        redisTemplate.opsForValue().set(SMS_CODE_PREFIX + phone, code, codeTtlSeconds, TimeUnit.SECONDS);
        if (smsMock) {
            log.info("[SMS-MOCK] 已发送验证码到 {}: {}", phone, code);
        } else {
            // TODO 接入真实短信通道
            log.info("[SMS] 已发送验证码到 {}", phone);
        }
    }

    // ---------- 登录 ----------

    @Override
    public Map<String, Object> login(String phone, String code) {
        ensureSmsLoginEnabled();
        if (!isValidPhone(phone)) {
            throw new BizException(UserErrorCode.INVALID_PHONE_FORMAT, "手机号格式错误");
        }
        if (!StringUtils.hasText(code)) {
            throw new BizException(UserErrorCode.VERIFICATION_CODE_REQUIRED, "验证码不能为空");
        }

        String redisKey = SMS_CODE_PREFIX + phone;
        String cached = redisTemplate.opsForValue().get(redisKey);
        if (!StringUtils.hasText(cached)) {
            throw new BizException(UserErrorCode.VERIFICATION_CODE_EXPIRED, "验证码已过期");
        }
        if (!cached.equals(code)) {
            throw new BizException(UserErrorCode.INVALID_VERIFICATION_CODE, "验证码错误");
        }

        User user = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getPhone, phone));
        if (user == null) {
            user = createUserBySmsLogin(phone);
            log.info("[Auth] 自动注册: phone={}, userId={}", phone, user.getId());
        } else if (user.getStatus() != null && user.getStatus() == 0) {
            throw new BizException(UserErrorCode.ACCOUNT_DISABLED, "账号已被禁用");
        }

        redisTemplate.delete(redisKey);
        log.info("[Auth] 登录成功: phone={}, userId={}", phone, user.getId());
        return generateTokenResponse(user);
    }

    // ---------- 查询 / 刷新 / 更新 ----------

    @Override
    public User getUserById(Long userId) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new BizException(UserErrorCode.USER_NOT_FOUND, "用户不存在");
        }
        return user;
    }

    @Override
    public Map<String, Object> refreshToken(String token) {
        String raw = jwtUtil.stripPrefix(token);
        if (raw == null || !jwtUtil.validate(raw)) {
            throw new BizException(UserErrorCode.INVALID_TOKEN, "token 无效或已过期");
        }
        Long userId = jwtUtil.getUserId(raw);
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new BizException(UserErrorCode.USER_NOT_FOUND, "用户不存在");
        }
        return generateTokenResponse(user);
    }

    @Override
    public User updateUserInfo(UpdateUserRequest request) {
        User user = userMapper.selectById(request.getUserId());
        if (user == null) {
            throw new BizException(UserErrorCode.USER_NOT_FOUND, "用户不存在");
        }
        if (StringUtils.hasText(request.getUsername())) {
            if (sensitiveWordUtil.contains(request.getUsername())) {
                throw new BizException(UserErrorCode.USERNAME_SENSITIVE, "用户名包含敏感词");
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

    // ---------- 私有 ----------

    private User createUserBySmsLogin(String phone) {
        User user = new User();
        user.setPhone(phone);
        user.setUsername("用户" + phone.substring(phone.length() - 4));
        // 短信登录用户没有真正的密码,给一个不可猜的随机密文占位
        user.setPassword(passwordEncoder.encode("sms-login-" + phone + "-" + System.currentTimeMillis()));
        user.setGender(0);
        user.setStatus(1);
        LocalDateTime now = LocalDateTime.now();
        user.setCreateTime(now);
        user.setUpdateTime(now);
        userMapper.insert(user);
        return user;
    }

    @Override
    public Map<String, Object> generateTokenResponse(User user) {
        return generateTokenResponse0(user);
    }

    private Map<String, Object> generateTokenResponse0(User user) {
        Map<String, Object> claims = new HashMap<>();
        claims.put("phone", user.getPhone());
        claims.put("username", user.getUsername());
        claims.put("role", "USER");

        String accessToken = jwtUtil.generateToken(user.getId(), claims);
        String refreshToken = jwtUtil.generateRefreshToken(user.getId());

        Map<String, Object> resp = new HashMap<>();
        resp.put("user", user);
        resp.put("token", accessToken);
        resp.put("refreshToken", refreshToken);
        resp.put("tokenType", "Bearer");
        return resp;
    }

    private boolean isValidPhone(String phone) {
        return phone != null && PHONE_PATTERN.matcher(phone).matches();
    }

    private void ensureSmsLoginEnabled() {
        if (!smsLoginEnabled) {
            throw new FeatureDisabledException(UserErrorCode.SMS_LOGIN_DISABLED,
                    "短信登录暂未开放，请使用体验登录");
        }
    }
}

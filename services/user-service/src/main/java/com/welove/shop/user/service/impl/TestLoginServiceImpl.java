package com.welove.shop.user.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.welove.shop.user.entity.User;
import com.welove.shop.user.mapper.UserMapper;
import com.welove.shop.user.service.AuthService;
import com.welove.shop.user.service.TestLoginService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 测试登录实现。
 * <p>
 * 每次体验登录创建一个独立测试账号。账号带 {@code is_test=true} 标识，
 * 避免不同浏览器或面试体验者共享聊天、收藏、订单等用户数据。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TestLoginServiceImpl implements TestLoginService {

    /** 测试手机号前缀，仅用于系统内体验账号标识，不走短信通道。 */
    private static final String TEST_PHONE_PREFIX = "198";

    private static final String TEST_PASSWORD_PLACEHOLDER = "test-login-placeholder";

    /** 11 位体验手机号剩余的 8 位数字空间。 */
    private static final long TEST_PHONE_SUFFIX_BOUND = 100_000_000L;

    /** 同一实例内单调分配，重启后仍会通过数据库存在性检查避开旧账号。 */
    private final AtomicLong phoneSequence = new AtomicLong(
            ThreadLocalRandom.current().nextLong(TEST_PHONE_SUFFIX_BOUND));

    private final UserMapper userMapper;
    private final AuthService authService;
    private final PasswordEncoder passwordEncoder;

    @Override
    @Transactional
    public Map<String, Object> testLogin() {
        User user = createFreshTestUser();

        // 体验账号也记录最后登录时间，供后续按 is_test 标记清理。
        user.setLastLoginAt(LocalDateTime.now());
        user.setUpdateTime(LocalDateTime.now());
        userMapper.updateById(user);

        log.info("[test-login] 创建并登录独立体验用户: phone={}, userId={}", user.getPhone(), user.getId());

        // 复用普通登录的 token 生成逻辑，前端和下游服务无需区分。
        return authService.generateTokenResponse(user);
    }

    // ---------- 私有 ----------

    private User createFreshTestUser() {
        for (int attempt = 0; attempt < 32; attempt++) {
            long suffix = Math.floorMod(phoneSequence.getAndIncrement(), TEST_PHONE_SUFFIX_BOUND);
            String phone = TEST_PHONE_PREFIX + String.format("%08d", suffix);
            boolean exists = userMapper.selectCount(
                    new LambdaQueryWrapper<User>().eq(User::getPhone, phone)) > 0;
            if (!exists) {
                return createTestUser(phone);
            }
        }
        throw new IllegalStateException("无法分配独立体验账号，请稍后重试");
    }

    private User createTestUser(String phone) {
        User user = new User();
        user.setPhone(phone);
        user.setUsername("体验用户_" + phone.substring(phone.length() - 4));
        user.setPassword(passwordEncoder.encode(TEST_PASSWORD_PLACEHOLDER));
        user.setGender(0);
        user.setStatus(1);
        user.setIsTest(true);
        LocalDateTime now = LocalDateTime.now();
        user.setCreateTime(now);
        user.setUpdateTime(now);
        userMapper.insert(user);
        log.info("[test-login] 创建测试账号: phone={}, userId={}", phone, user.getId());
        return user;
    }
}

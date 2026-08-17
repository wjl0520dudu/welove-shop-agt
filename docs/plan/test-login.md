# 测试登录接入文档

> **状态**：独立体验账号登录、Redis 配额与演示环境开关已落地 ✅；自动清理任务仅文档占位 ⏳
> **目的**：给"想快速体验系统的人"一个一键登录通道，跳过手机号 + 验证码流程。
> **设计原则**：安全可控、易清理、不污染真实用户数据。

---

## 1. 背景

目前登录流程：

```
打开 login.vue → 输入手机号 → 点"获取短信验证码"
  → 跳到 login-code.vue → 输入 6 位验证码 → 登录
```

体验成本偏高（4 步 + 验证码），不利于演示和邀请体验。

**目标**：用户点一次按钮 → 直接进首页 → 像正常登录一样操作。

---

## 2. 接口设计

### 2.1 接口

```
POST /api/auth/test-login
Content-Type: application/json

(无请求体)
```

**响应（与 `/auth/login` 完全一致）**：

```json
{
  "code": 0,
  "message": "success",
  "success": true,
  "data": {
    "tokenType": "Bearer",
    "token": "eyJhbGciOiJIUzUxMiJ9...",
    "refreshToken": "eyJhbGciOiJIUzUxMiJ9...",
    "user": {
      "id": 15,
      "username": "体验用户_0002",
      "phone": "19801234567",
      "avatarUrl": null,
      "gender": 0,
      "ageRange": null,
      "skinType": null,
      "preferenceTags": null,
      "status": 1,
      "isTest": true,
      "lastLoginAt": "2026-07-21T00:21:58.9141162",
      "createTime": "2026-07-21T00:17:12.892194",
      "updateTime": "2026-07-21T00:21:58.9141162"
    }
  }
}
```

### 2.2 关键设计

| 项 | 值 | 理由 |
|---|---|---|
| 手机号前缀 | `198` + 8 位数字 | 仅作为系统内体验账号标识，不走短信通道 |
| 账号策略 | 每次登录创建独立账号 | 不同体验者不会共享聊天、收藏、地址或订单数据 |
| 账号分配 | 进程内序列 + 数据库存在性检查 | 同一实例单调分配；重启后自动跳过既有号码 |
| 白名单 | `/auth/test-login` | 见 [WebMvcConfig.java](../../services/user-service/src/main/java/com/welove/shop/user/config/WebMvcConfig.java) |
| 响应结构 | 与 `/auth/login` 一致 | 前端无感，登录后所有逻辑统一 |

### 2.3 用户标记

`user.isTest = true` 标识此账号是测试账号。前端可据此：
- 在用户中心显示"体验账号"角标
- 屏蔽"修改密码"等高敏感操作
- 显示"清理提醒"提示

---

## 3. 频控（防滥用）

### 3.1 策略

| 维度 | 默认值 | 说明 |
|---|---|---|
| 单 IP | 3 次 / 10 分钟 | 防连续点击和简单脚本 |
| 单 IP | 10 次 / 天 | 防低频持续创建账号 |
| 全局 | 100 次 / 小时 | 防多 IP 协同异常写入 |
| 全局 | 500 次 / 天 | 限制演示环境单日账号增长 |

### 3.2 实现

[Redis 计数器](../../services/user-service/src/main/java/com/welove/shop/user/controller/TestLoginController.java)：

```
test-login:ip:10m:{ip}    → INCR + EXPIRE 10m
test-login:ip:day:{ip}    → INCR + EXPIRE 1d
test-login:global:hour    → INCR + EXPIRE 1h
test-login:global:day     → INCR + EXPIRE 1d
```

超出 → HTTP `429 Too Many Requests`，响应 `code: 20201 TEST_LOGIN_RATE_LIMIT`。

### 3.3 可配置

在 application.yml 调整（dev 默认值）：

```yaml
user-service:
  test-login:
    enabled: true
    ip-rate-per-10-minutes: 3
    ip-rate-per-day: 10
    global-rate-per-hour: 100
    global-rate-per-day: 500
```

### 3.4 客户端 IP 解析

```
X-Forwarded-For → 取第一段（由公网 Nginx 覆盖写入）
X-Real-IP       → 取值
remoteAddr      → fallback
```

⚠️ **生产环境必须保持 Nginx 覆盖客户端自带的 XFF**：外部请求不能自行决定该字段，否则攻击者可以伪造 IP 绕过单 IP 配额。

---

## 4. 临时账号清理任务（⏳ 仅文档）

### 4.1 为什么需要清理

- 每次体验登录都会生成测试账号，长期积累会增加用户表及关联业务数据
- 测试账号的订单 / 收藏 / 地址会留在用户表关联数据里
- 真实用户看到"19800000001"这种手机号时会困惑

### 4.2 清理策略设计（待实现）

**触发**：Spring `@Scheduled` 每天凌晨 3:00 跑一次。

**清理逻辑**：

```sql
-- 软删:is_test=true AND (last_login_at IS NULL OR last_login_at < now() - 7 days)
UPDATE users SET status = 0 WHERE is_test = TRUE
  AND (last_login_at IS NULL OR last_login_at < now() - interval '7 days');
```

**选项**：
- **A. 软删**（推荐）：`status=0`，账号不能登录但数据保留；后续分析"体验用户行为"还能用
- **B. 硬删**：彻底删除 + 级联删除关联数据（订单 / 地址 / 收藏）

建议先用 A，30 天后再 B（数据清理到位再硬删）。

### 4.3 实现代码骨架

> 当前不实现，仅留接口设计。

```java
@Service
@RequiredArgsConstructor
public class TestAccountCleanupTask {

    private final UserMapper userMapper;

    /**
     * 每天凌晨 3 点扫描 7 天未登录的测试账号,标记为禁用。
     */
    @Scheduled(cron = "0 0 3 * * ?")
    @Transactional
    public void cleanup() {
        int disabled = userMapper.disableInactiveTestAccounts(7);
        log.info("[test-cleanup] disabled {} inactive test accounts", disabled);
    }
}
```

```xml
<!-- pom.xml 启用 @Scheduled -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter</artifactId>
</dependency>

<!-- Application 启用调度 -->
@EnableScheduling
public class UserServiceApplication { ... }
```

### 4.4 接入这个任务时需要做的事

1. 加 `UserMapper.disableInactiveTestAccounts(int days)` 方法
2. 写 `@Scheduled` 任务类
3. `@EnableScheduling` 加到 UserServiceApplication
4. 配置 `cron` 在 application.yml（默认即可）
5. 写日志监控：每天清理数量记录到指标系统
6. 监控告警：如果某天清理数 > N（比如 1000）发告警，可能有异常

---

## 5. 前端集成

### 5.1 UI 改动

[login.vue](../../web/welove-shop/src/pages/login/login.vue) 加按钮：

```vue
<button class="login-button" @tap="handleGetCode">获取短信验证码</button>

<view class="divider-row">
  <view class="line"></view>
  <text class="or">或</text>
  <view class="line"></view>
</view>

<button class="test-login-button" :loading="testLoading" @tap="handleTestLogin">
  体验登录(无需手机号)
</button>
```

### 5.2 调用

```js
async handleTestLogin() {
  const data = await testLogin()   // 后端返回 {token, refreshToken, user}
  await userStore.handleTestLogin(data)   // 存 token 到 store + localStorage
  uni.switchTab({ url: '/pages/product-list/product-list' })
}
```

---

## 6. 验证清单

接入后跑以下 6 项：

- [ ] **数据库迁移成功**：Flyway V2 跑过，`users` 表新增 `is_test` + `last_login_at` 两列
- [ ] **独立账号创建**：连续调用两次 `/auth/test-login`，返回的 `user.id` 必须不同
- [ ] **测试登录成功**：`curl POST /auth/test-login` 返回 token + user
- [ ] **频控生效**：连点 6 次，第 6 次返回 `code: 20201`
- [ ] **前端登录页有按钮**：`<体验登录(无需手机号)>` 按钮可点
- [ ] **跳首页成功**：点完按钮，自动跳到 `/pages/product-list/product-list`，token 存到 localStorage

---

## 7. FAQ

### Q1：为什么不直接给所有人发 admin token？

A：admin 权限太大，会绕过 user-service 的 userId 校验，影响下游 trade-service 的权限判断。体验账号仍然是普通 user，只是免登录。

### Q2：测试账号能下单/支付吗？

A：能。和正常用户走完全一样的业务链路。体验账号不会被其他体验者复用；但仍建议前端根据 `user.isTest=true` 对支付、密码修改等高风险操作给出明确提示。

### Q3：不同浏览器的体验用户会互相看到数据吗？

A：不会。每次点击“体验登录”都会创建一个新的 `is_test=true` 用户，因此 Edge、Chrome 或不同面试体验者会获得不同的 `userId`，聊天、收藏、地址和订单数据隔离。

同一浏览器已登录后刷新页面会继续使用本地保存的 JWT；只有主动退出后再次点击“体验登录”才会创建另一个新体验账号。

### Q4：生产环境能用吗？

A：**不建议对公网生产环境开放**。
- 每次调用都会创建测试用户，仍可能被恶意请求制造数据；必须保留频控，并建议在生产关闭该接口
- 生产应该走正常短信验证
- 建议在生产环境 application-prod.yml 设 `user-service.test-login.ip-rate-per-minute: 0` 或者直接 disable 接口

### Q5：清理任务什么时候做？

A：当前不实现（**等后续 sprint**）。上线初 1-2 周观察数据量决定。

---

## 8. 相关文档

- [alipay-sandbox-payment.md](./alipay-sandbox-payment.md) — 另一种"免登录体验"路径（直接下单付款）
- [nacos-config-center.md](./nacos-config-center.md) — Nacos 配置中心，本功能通过 `user-service.test-login.*` 配置

---

**变更记录**
- 2026-07-21: 实现测试登录接口 + 频控 + 共享测试账号池；清理任务仅文档占位
- 2026-08-10: 改为每次登录创建独立体验账号，避免多浏览器和多体验者共享数据

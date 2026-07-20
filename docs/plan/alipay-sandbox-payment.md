# 支付宝沙箱支付集成 — 开发文档

> **服务**：`trade-service`（port 8083）
> **目标**：在现有"模拟支付"基础上，接入支付宝沙箱（Alipay Sandbox）真实支付链路，覆盖**下单 → 发起支付 → 异步通知 → 订单状态变更**全流程。
> **范围**：MVP 阶段默认做"手机 H5 支付（WAP）+ 异步通知 + 订单查询 + 订单关闭"四个核心场景，同时保留 PC Page 模式兼容；退款、退款查询留给后续迭代。
> **技术选型**：`alipay-easysdk 2.2.2`（官方主推，链式 API，新项目首选）。
> **状态机**：沿用 trade-service 现有 0~4 状态机；本任务只触碰 `0 → 1` 这一条边。

---

## 0. 背景与现状

### 0.1 trade-service 现有支付代码

`OrderServiceImpl#payOrder` 当前是**直接更新数据库**的"假支付"：

```java
// OrderServiceImpl.java:196-207（当前实现）
@Override
@Transactional
public void payOrder(Long userId, Long orderId) {
    Order order = requireOwnedOrder(userId, orderId);
    if (order.getStatus() != 0) {
        throw new BizException(TradeErrorCode.ORDER_STATUS_INVALID, "订单状态不允许支付");
    }
    LocalDateTime now = LocalDateTime.now();
    order.setStatus(1);
    order.setPayTime(now);
    order.setUpdateTime(now);
    orderMapper.updateById(order);
}
```

Controller `PUT /order/{id}/pay` 直接调它，没有任何外部支付集成。AGENTS.md（trade-service）也明确写了 *"Order creation, list, detail, cancel, payment simulation, shipping, and completion"* —— 当前就是 simulation。

### 0.2 接入后改动面（最小化）

| 改动 | 必做 | 说明 |
|---|---|---|
| `orders` 表加 `pay_channel` / `trade_no` 字段 | ✅ | 记录支付渠道 + 支付宝交易号，方便对账 |
| 新增 `AlipayController` 发起支付 | ✅ | 默认 H5 收银台，支持切回 PC |
| 新增 `AlipayNotifyController` 接 notify | ✅ | 异步验签 + 幂等更新订单 |
| `OrderService#payOrder` 行为变 | ✅ | 不再直接改状态；改为"创建支付单"语义，返回支付 URL 由前端跳转 |
| `OrderService#handlePayNotify`（新增） | ✅ | 回调验签后调用，幂等更新 0 → 1 |
| `WebMvcConfig` 白名单 | ✅ | 回调地址必须免鉴权 |
| `application.yml` + `pom.xml` | ✅ | 加 SDK、加配置项 |
| `TradeErrorCode` 新增支付域错误码 | ✅ | 40xxx 中分一段 |
| gateway / admin-bff | ❌ | 本次不动，路径全在 trade-service 内部 |

### 0.3 不动的东西

- `payOrder` 现有 0 → 1 逻辑保留（作为"线下补单/管理员手动支付"路径，不删除）
- `OrderTimeoutTask` 继续负责超时关单
- `OrderVO` 字段不动（前端不变），payChannel/tradeNo 走 `extra` 字段或下个 PR 单独加

---

## 1. 微服务归属评估

| 候选服务 | 评估 | 结论 |
|---|---|---|
| **trade-service**（order/cart/payment simulation 都在这里） | ✅ 数据 owner 正确（order 表在 `trade_svc`），业务边界清晰，与现有 payOrder/cancel 强相关 | **选用** |
| chat-service | ❌ 只管会话/消息，不持订单 | 不选 |
| gateway | ❌ 入口路由，不存业务数据 | 不选 |
| admin-bff | ❌ 只聚合/转发，无业务库 | 不选 |
| 新建 payment-service | ❌ 骨架期不分层；后续若要"多渠道支付"再抽 | 不选 |

**结论**：在 **trade-service** 内做。新增 `controller/alipay/AlipayController.java` + `controller/alipay/AlipayNotifyController.java` + `service/PaymentService.java` + `service/impl/PaymentServiceImpl.java` + `config/AlipayConfig.java` + `dto/PayResponse.java`。

---

## 2. 支付宝沙箱支付流程

### 2.1 端到端时序

```
┌────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────┐
│ 用户前端 │     │ trade-service │     │ 支付宝沙箱     │     │  沙箱 APP │
└───┬────┘     └──────┬───────┘     └──────┬───────┘     └────┬───┘
    │ 1. 点击"去支付"  │                       │                  │
    │ ───────────────►│                       │                  │
    │                 │ 2. 校验订单 0 态        │                  │
    │                 │ 3. 调 easysdk.Page().pay() │
    │                 │ ─────────────────────►│                  │
    │                 │ 4. 返回 form HTML      │                  │
    │ 5. 自动提交 form │ ◄─────────────────────│                  │
    │ ───────────────►│                       │                  │
    │                                                   │ 6. 沙箱买家账号
    │                                                   │    密码 111111 付款
    │                 │ 7. notify POST ───────►│                  │
    │                 │ 8. 验签(rsaCheckV1)   │                  │
    │                 │ 9. 幂等更新 0 → 1      │                  │
    │                 │ 10. 返回 "success"  ──►│                  │
    │                 │                       │                  │
    │ 11. return GET  │                       │                  │
    │ ◄────────────────────────────────────────│                  │
    │ 12. 前端轮询 /api/trade/order/{id}        │                  │
    │    看到 status=1 → 跳"支付成功"页          │                  │
```

### 2.2 关键规则（必须遵守）

1. **业务逻辑必须放在 `notify_url`**，不能依赖 `return_url`（return_url 用户关页面就不触发）
2. **验签用的是"支付宝公钥"**，不是"应用公钥"（沙箱后台自动生成那段）
3. **notify 响应必须纯字符串 `success`**，不能含任何 HTML/JSON/换行
4. **业务处理必须幂等**（按 `out_trade_no` + `status=0` 的 `updateById` 影响行数判断）
5. **金额校验**：验签通过后必须再校验回调 `total_amount` == 本地 `pay_amount`，防伪造
6. **沙箱网关**：`https://openapi.alipaydev.com/gateway.do`（生产是 `https://openapi.alipay.com/gateway.do`）
7. **HTTPS 强制**：回调地址必须公网 HTTPS，详见 §6

### 2.3 选型说明

| 选型 | 决定 | 理由 |
|---|---|---|
| `alipay-easysdk 2.2.2` | ✅ | 官方主推，链式 API，少量代码；2026 年新接入首选 |
| `alipay-sdk-java 4.x` | ❌ | 老 SDK，基础维护；存量项目保留，新项目不用 |
| H5 手机网站支付 (`alipay.trade.wap.pay`) | ✅ MVP | 与 uni-app H5 前端一致 |
| PC 电脑网站支付 (`alipay.trade.page.pay`) | ✅ 兼容 | 通过 `alipay.pay-mode=page` 切换 |
| 不做证书模式（PKCS12） | ✅ MVP | 公钥模式够用，证书模式上线再切 |
| 不做退款 | ✅ MVP | 留到下个迭代；本期 VO 也不返 tradeNo，避免前端依赖 |

---

## 3. 数据库迁移（Flyway V2）

### 3.1 文件位置

`services/trade-service/src/main/resources/db/migration/V2__add_payment_columns_to_orders.sql`

### 3.2 SQL

```sql
-- =====================================================================
-- V2: 支付宝沙箱支付接入 — orders 表加支付渠道与支付宝交易号
-- schema: trade_svc
-- 字段:
--   pay_channel: 支付渠道,默认 'MOCK'(模拟),接沙箱后为 'ALIPAY_SANDBOX'
--   trade_no:    支付宝交易号(异步通知里拿到,TRADE_SUCCESS 之后写)
-- 索引: trade_no 用唯一索引(幂等键),但允许 NULL(未支付订单)
-- =====================================================================

SET search_path TO trade_svc;

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS pay_channel VARCHAR(20) NOT NULL DEFAULT 'MOCK',
    ADD COLUMN IF NOT EXISTS trade_no    VARCHAR(64);

COMMENT ON COLUMN orders.pay_channel IS '支付渠道: MOCK(模拟) / ALIPAY_SANDBOX(支付宝沙箱) / 未来加 WECHAT/ALIPAY_PROD 等';
COMMENT ON COLUMN orders.trade_no    IS '支付宝交易号(异步通知里回传,TRADE_SUCCESS 后写入)';

-- trade_no 部分唯一索引(允许 NULL 重复,但非 NULL 必须唯一)
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_trade_no ON orders(trade_no) WHERE trade_no IS NOT NULL;
```

**为什么用部分唯一索引**：未支付订单 `trade_no` 仍为 NULL，多笔订单同时为 NULL 不算冲突（PG 允许 NULL 重复）；一旦有 tradeNo 写入则必须唯一。

---

## 4. Maven 依赖

在 `services/trade-service/pom.xml` 的 `<dependencies>` 末尾添加：

```xml
<!-- 支付宝 EasySDK(沙箱/生产通用,2026 新接入首选) -->
<dependency>
    <groupId>com.alipay.sdk</groupId>
    <artifactId>alipay-easysdk</artifactId>
    <version>2.2.2</version>
</dependency>
```

**注意**：不需要额外引入 `alipay-sdk-java`，easysdk 已包含底层。

---

## 5. 配置文件

### 5.1 `application.yml`（追加）

在 `jwt:` 段后追加：

```yaml
# ---------- 支付宝支付 ----------
alipay:
  # 沙箱环境(开发期使用),上线需切换为生产参数
  app-id: ${ALIPAY_APP_ID:2021000123456789}
  app-private-key: ${ALIPAY_APP_PRIVATE_KEY:}      # PKCS8 格式,无 -----BEGIN/END-----
  alipay-public-key: ${ALIPAY_ALIPAY_PUBLIC_KEY:}  # 支付宝公钥,非应用公钥
  gateway-url: ${ALIPAY_GATEWAY:https://openapi-sandbox.dl.alipaydev.com/gateway.do}
  pay-mode: ${ALIPAY_PAY_MODE:wap}
  sign-type: RSA2
  charset: UTF-8
  protocol: https
  # 回调地址(必须公网 HTTPS,内网穿透详见 §6)
  notify-url: ${ALIPAY_NOTIFY_URL:https://pay-dev.example.com/api/trade/alipay/notify}
  return-url: ${ALIPAY_RETURN_URL:https://pay-dev.example.com/api/trade/alipay/return}
  # 沙箱开关:false = 走"模拟支付"老路径,便于本地无配置时跑通
  enabled: ${ALIPAY_ENABLED:false}
```

### 5.2 `.env.example`（仓库根）

追加：

```bash
# 支付宝沙箱(开发期)
ALIPAY_ENABLED=true
ALIPAY_APP_ID=2021000123456789
ALIPAY_APP_PRIVATE_KEY=           # 从支付宝签名验签工具生成,粘贴 PKCS8 私钥
ALIPAY_ALIPAY_PUBLIC_KEY=         # 沙箱后台"应用公钥"提交后,平台返回的"支付宝公钥"
ALIPAY_GATEWAY=https://openapi.alipaydev.com/gateway.do
ALIPAY_NOTIFY_URL=https://your-cpolar-or-cloudflared-domain.com/api/trade/alipay/notify
ALIPAY_RETURN_URL=https://your-cpolar-or-cloudflared-domain.com/api/trade/alipay/return
```

---

## 6. 内网穿透方案（用户后面会单独配，本节只给推荐）

> 支付宝沙箱要求 `notify_url` 是**公网可访问的 HTTPS**。Windows 本地 8080 端口必须穿透出去。

### 6.1 推荐方案

| 方案 | 适合 | 域名稳定性 | 代价 |
|---|---|---|---|
| ⭐ **cloudflared 命名隧道 + 自购域名**（如 `.xyz` ¥10/年） | 长期开发 | **永久稳定** | 需买一个便宜域名 + 改 NS |
| **frp + 自有 VPS** | 已有公网服务器 | 完全自控 | 需一台 VPS + 配 Nginx/证书 |
| **cpolar 免费版** | 临时/单次 | 24h 变一次 | 每次重启要改沙箱后台 |

**推荐使用 `cloudflared 命名隧道`**：
```bash
cloudflared tunnel create alipay-dev
cloudflared tunnel route dns alipay-dev pay-dev.yourdomain.xyz
cloudflared tunnel run alipay-dev
# 然后把 pay-dev.yourdomain.xyz 填到 ALIPAY_NOTIFY_URL
```

### 6.2 用户后续要做的（不在本次开发范围）

1. 自购一个便宜域名（如 `.xyz` / `.top`），把 NS 改到 Cloudflare
2. 安装 cloudflared，建命名隧道
3. 把穿透出来的 `https://pay-dev.yourdomain.xyz/api/trade/alipay/notify` 填到：
   - `.env` 的 `ALIPAY_NOTIFY_URL`
   - 支付宝沙箱后台"应用配置"里的"授权回调地址"

---

## 7. 代码实现清单

### 7.1 新增文件

| 文件 | 作用 |
|---|---|
| `config/AlipayConfig.java` | 读 yml，注入 `AlipayClient`（SDK 实例） |
| `service/PaymentService.java` + `impl/PaymentServiceImpl.java` | 支付域业务：createPay / handleNotify / query / close |
| `controller/alipay/AlipayController.java` | 用户端：发起支付、查询、关闭 |
| `controller/alipay/AlipayNotifyController.java` | 支付宝回调端（**白名单免鉴权**） |
| `dto/PayResponse.java` | 发起支付返回：含支付跳转 form |
| `dto/AlipayNotifyDTO.java` | 回调参数映射（可选，主要在 Controller 内 Map 接收） |
| `dto/PayStatusVO.java` | 查询结果 VO |

### 7.2 改动文件

| 文件 | 改动 |
|---|---|
| `entity/Order.java` | 加 `payChannel`、`tradeNo` 字段 |
| `service/OrderService.java` | `payOrder` 保留旧行为 + 新增 `markPaidByCallback(outTradeNo, tradeNo, totalAmount, channel)` |
| `service/impl/OrderServiceImpl.java` | 实现 `markPaidByCallback`，幂等更新 0 → 1 |
| `exception/TradeErrorCode.java` | 加 403xx 段（支付域） |
| `config/WebMvcConfig.java` | 白名单加 `/alipay/notify` |
| `application.yml` | 加 `alipay:` 段（§5.1） |
| `pom.xml` | 加 easysdk 依赖（§4） |
| `db/migration/V2__add_payment_columns_to_orders.sql` | 加字段 + 部分唯一索引（§3） |

---

## 8. 核心代码骨架（落地参考）

### 8.1 `AlipayConfig.java`

```java
package com.welove.shop.trade.config;

import com.alipay.easysdk.factory.Factory;
import com.alipay.easysdk.kernel.Config;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;

@Slf4j
@Configuration
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "alipay", name = "enabled", havingValue = "true")
public class AlipayConfig {

    @Value("${alipay.app-id}")             private String appId;
    @Value("${alipay.app-private-key}")    private String appPrivateKey;
    @Value("${alipay.alipay-public-key}")  private String alipayPublicKey;
    @Value("${alipay.gateway-url}")        private String gatewayUrl;
    @Value("${alipay.protocol}")           private String protocol;
    @Value("${alipay.sign-type}")          private String signType;
    @Value("${alipay.charset}")            private String charset;

    @PostConstruct
    public void init() {
        // gatewayUrl 形如 https://openapi.alipaydev.com/gateway.do
        // 拆出 host(openapi.alipaydev.com)
        String host = gatewayUrl.replace("https://", "").replace("http://", "")
                                .replace("/gateway.do", "");
        Config config = new Config();
        config.protocol = protocol;
        config.gatewayHost = host;
        config.appId = appId;
        config.signType = signType;
        config.merchantPrivateKey = appPrivateKey;
        config.alipayPublicKey = alipayPublicKey;
        config.charset = charset;
        Factory.setOptions(config);
        log.info("[alipay] easysdk initialized, gateway={}, appId={}", host, appId);
    }
}
```

### 8.2 `PaymentService.java` 接口

```java
public interface PaymentService {
    /** 发起支付,返回收银台 form HTML(给前端直接渲染)。 */
    String createPayPage(Long userId, Long orderId);

    /** 处理支付宝异步通知(在 Controller 内验签后调用)。 */
    void handlePayNotify(Map<String, String> params);

    /** 查询支付宝订单状态(主动对账用)。 */
    PayStatusVO queryTradeStatus(Long userId, Long orderId);

    /** 关闭未支付订单(同步关支付宝+本地)。 */
    void closePay(Long userId, Long orderId);
}
```

### 8.3 `PaymentServiceImpl#createPayPage`（核心）

```java
@Override
public String createPayPage(Long userId, Long orderId) {
    Order order = requireOwnedOrder(userId, orderId);
    if (order.getStatus() != 0) {
        throw new BizException(TradeErrorCode.ORDER_STATUS_INVALID, "订单状态不允许支付");
    }
    try {
        // outTradeNo 用我们自己的 orderNo,方便回调对账
        AlipayTradePagePayResponse resp = Factory.Payment.Page()
                .pay(buildSubject(order),
                     order.getOrderNo(),
                     order.getPayAmount().toPlainString(),
                     alipayProps.getReturnUrl(),
                     alipayProps.getNotifyUrl());
        // body 是 form HTML,前端直接渲染
        return resp.getBody();
    } catch (Exception e) {
        log.error("[alipay] createPayPage failed, orderNo={}", order.getOrderNo(), e);
        throw new BizException(TradeErrorCode.PAY_CREATE_FAILED, "创建支付单失败:" + e.getMessage());
    }
}

private String buildSubject(Order order) {
    return "WeLove Shop 订单 " + order.getOrderNo();
}
```

### 8.4 `PaymentServiceImpl#handlePayNotify`（核心 — 幂等）

```java
@Override
@Transactional
public void handlePayNotify(Map<String, String> params) {
    String outTradeNo = params.get("out_trade_no");
    String tradeNo    = params.get("trade_no");
    String tradeStatus = params.get("trade_status");
    String totalAmount = params.get("total_amount");

    if (outTradeNo == null) {
        throw new BizException(TradeErrorCode.PAY_NOTIFY_INVALID, "out_trade_no 缺失");
    }

    Order order = orderMapper.selectOne(
        new LambdaQueryWrapper<Order>().eq(Order::getOrderNo, outTradeNo));
    if (order == null) {
        throw new BizException(TradeErrorCode.ORDER_NOT_FOUND, "订单不存在:" + outTradeNo);
    }

    // 金额校验(防伪造)
    if (totalAmount != null
        && new BigDecimal(totalAmount).compareTo(order.getPayAmount()) != 0) {
        log.warn("[alipay-notify] amount mismatch, orderNo={}, notify={}, local={}",
                 outTradeNo, totalAmount, order.getPayAmount());
        throw new BizException(TradeErrorCode.PAY_NOTIFY_INVALID, "金额不一致");
    }

    // 幂等:仅 status=0 时更新
    if (order.getStatus() != 0) {
        log.info("[alipay-notify] already processed, orderNo={}, status={}", outTradeNo, order.getStatus());
        return;
    }

    if ("TRADE_SUCCESS".equals(tradeStatus) || "TRADE_FINISHED".equals(tradeStatus)) {
        LocalDateTime now = LocalDateTime.now();
        order.setStatus(1);
        order.setPayTime(now);
        order.setUpdateTime(now);
        order.setTradeNo(tradeNo);
        order.setPayChannel("ALIPAY_SANDBOX");
        orderMapper.updateById(order);
        log.info("[alipay-notify] order paid, orderNo={}, tradeNo={}", outTradeNo, tradeNo);
    } else if ("TRADE_CLOSED".equals(tradeStatus)) {
        // 支付宝侧已关闭(超时未付),本地也置为取消 4
        order.setStatus(4);
        order.setUpdateTime(LocalDateTime.now());
        order.setTradeNo(tradeNo);
        orderMapper.updateById(order);
    }
    // WAIT_BUYER_PAY 不处理,等下次通知
}
```

### 8.5 `AlipayNotifyController`（白名单端点）

```java
@RestController
@RequestMapping("/alipay")
@RequiredArgsConstructor
public class AlipayNotifyController {

    private final PaymentService paymentService;
    @Value("${alipay.alipay-public-key}") private String alipayPublicKey;

    /**
     * 异步通知 — 必须返回纯字符串 "success"。
     * 路径必须在 WebMvcConfig 白名单(免鉴权)。
     */
    @PostMapping("/notify")
    public String notify(HttpServletRequest request) {
        Map<String, String> params = new HashMap<>();
        request.getParameterMap().forEach((k, v) -> {
            if (!"sign".equals(k) && !"sign_type".equals(k)) {
                params.put(k, v[0]);
            }
        });
        try {
            // 验签 — rsaCheckV1(params, 公钥, charset, signType)
            boolean ok = AlipaySignature.rsaCheckV1(
                params, alipayPublicKey, "UTF-8", "RSA2");
            if (!ok) {
                log.warn("[alipay-notify] signature verification failed, params={}", params);
                return "fail";
            }
            paymentService.handlePayNotify(params);
            return "success";
        } catch (Exception e) {
            log.error("[alipay-notify] handle error", e);
            return "fail";
        }
    }

    /**
     * 同步跳转 — 仅展示,不依赖业务逻辑。
     * 路径也在白名单。
     */
    @GetMapping("/return")
    public String returnUrl(HttpServletRequest request) {
        return "支付完成,请回到订单列表查看状态";
    }
}
```

### 8.6 `AlipayController`（用户端）

```java
@RestController
@RequestMapping("/alipay")
@RequiredArgsConstructor
public class AlipayController {

    private final PaymentService paymentService;

    /** 发起支付宝网页支付 — 默认 H5 WAP,可切换为 PC Page。 */
    @PostMapping(value = "/create/{orderId}", produces = "text/html;charset=UTF-8")
    public String create(@PathVariable Long orderId) {
        return paymentService.createPayPage(UserContext.requireUserId(), orderId);
    }

    /** 主动查询支付状态(对账/前端轮询用)。 */
    @GetMapping("/status/{orderId}")
    public Result<PayStatusVO> status(@PathVariable Long orderId) {
        return Result.ok(paymentService.queryTradeStatus(UserContext.requireUserId(), orderId));
    }

    /** 主动关闭(用户取消支付时)。 */
    @PostMapping("/close/{orderId}")
    public Result<Void> close(@PathVariable Long orderId) {
        paymentService.closePay(UserContext.requireUserId(), orderId);
        return Result.ok();
    }
}
```

### 8.7 `WebMvcConfig` 白名单补充

```java
private static final List<String> WHITELIST = List.of(
        "/internal/**",
        "/alipay/notify",       // 支付宝异步通知(公网调用,无 JWT)
        "/alipay/return",       // 支付宝同步跳转(浏览器 GET,无 JWT)
        "/actuator/**",
        "/error"
);
```

### 8.8 `TradeErrorCode` 新增

```java
// ---------- 支付域(403xx)----------
public static final int PAY_CREATE_FAILED   = 40301;  // 发起支付失败
public static final int PAY_NOTIFY_INVALID  = 40302;  // 回调参数非法/验签失败/金额不一致
public static final int PAY_QUERY_FAILED    = 40303;  // 查询失败
public static final int PAY_CLOSE_FAILED    = 40304;  // 关闭失败
```

### 8.9 `entity/Order.java` 字段补充

```java
/** 支付渠道:MOCK(模拟)/ALIPAY_SANDBOX/未来加 WECHAT/ALIPAY_PROD 等。 */
private String payChannel;

/** 支付宝交易号(异步通知里回传)。 */
private String tradeNo;
```

`OrderVO` 本期**不动**，前端不感知（tradeNo 走下个 PR 单独加）。

---

## 9. 验证步骤（端到端）

> 本地无外网时，**降级为仅测 `MOCK` 路径**（`ALIPAY_ENABLED=false`）；真实沙箱需穿透，详见 §6。

### 9.1 编译验证

```bash
mvn -pl services/trade-service -am compile
```

### 9.2 启动验证

```bash
mvn -pl services/trade-service spring-boot:run
# 健康
curl http://localhost:8083/actuator/health
```

### 9.3 沙箱端到端（需先做 §6 内网穿透 + 沙箱后台配授权回调地址）

1. 登录获取 JWT → 用 `POST /api/user/auth/login` 拿 token
2. 创建一个订单（cart 流程省略，直接 `POST /api/trade/order/create`）→ 拿 `orderId`
3. **调支付**：`POST /api/trade/alipay/create/{orderId}` 携带 Authorization header → 返回 form HTML
4. 把 form 渲染到浏览器 → 跳转沙箱收银台 → 用沙箱买家账号(`xxx@sandbox.com` / 密码 `111111`)付款
5. 看日志：trade-service 应打出 `[alipay-notify] order paid, orderNo=...`
6. 查订单：`GET /api/trade/order/{id}` → `status=1`,`payTime` 有值
7. 主动轮询：`GET /api/trade/alipay/status/{orderId}` → 应返 `tradeStatus=TRADE_SUCCESS`

### 9.4 关键日志

- `[alipay] easysdk initialized, gateway=...` — 启动成功
- `[alipay-notify] signature verification failed` — 验签失败,检查 `alipay.alipay-public-key` 配置
- `[alipay-notify] amount mismatch` — 金额对不上,检查 pay_amount 字段
- `[alipay-notify] already processed` — 重复通知(幂等正常)

### 9.5 沙箱后台要填的两处

| 位置 | 填什么 |
|---|---|
| 沙箱应用 → 应用配置 → 授权回调地址 | `https://你的穿透域名/api/trade/alipay/notify`(仅 notify 路径) |
| 签名验签工具 | RSA2 + PKCS8,生成后把"应用公钥"贴到沙箱后台,平台返回的"支付宝公钥"贴到 `.env` 的 `ALIPAY_ALIPAY_PUBLIC_KEY` |

---

## 10. 风险与回退

| 风险 | 缓解 |
|---|---|
| 沙箱/穿透域名挂掉,本地跑不通 | `ALIPAY_ENABLED=false` → 走原 MOCK 路径,业务不阻塞 |
| 用户关支付页,return_url 没触发 | 业务逻辑全部在 notify,前端用 2s 轮询 `GET /alipay/status/{id}` 兜底 |
| 验签用的公钥配错 | 启动时 easysdk 不验证公钥格式,只能等回调时失败 → 增加启动期 base64 解码自检(可选增强) |
| 通知重发导致重复更新 | `updateById` + 业务幂等检查(status=0 才更新)+ `trade_no` 部分唯一索引 |
| 沙箱公私钥泄到 git | `.env` 进 `.gitignore`;SDK 配置项用 `${ENV:default}` 模式,文档不给示例私钥 |
| 订单已超时(状态=4)时,异步通知才到 | `handlePayNotify` 查订单时若 `status=4` 且 tradeStatus=SUCCESS,日志告警并人工介入(不做自动复活) |

---

## 11. 后续迭代(不在本期)

- [x] H5 支付 (`alipay.trade.wap.pay`) — 适配移动端
- [ ] 退款 (`alipay.trade.refund`) + 退款查询
- [ ] 订单 `OrderVO` 暴露 `payChannel` / `tradeNo` 给前端
- [ ] 主动对账定时任务(每 5 分钟拉 `alipay.trade.query` 补漏)
- [ ] 切换正式支付宝(`gateway-url` + `app-id` + 证书)
- [ ] 抽 `payment-service` 微服务(若未来要做微信/银联等多渠道)

---

## 12. 文档交叉引用

- 项目根 `AGENTS.md` —— 后端规范、JWT 拦截、Flyway 约定
- `services/trade-service/AGENTS.md` —— 订单状态机、Feign 跨服务规范
- `docs/plan/` 目录其它方案文档

---

# 附录:开发者接入指南(手把手)

> 本节是给"完全没接过支付宝沙箱"的开发者写的——按顺序从 0 到 1 走一遍,每步都给你具体在哪里点、填什么、复制哪段命令。预计耗时 **20-30 分钟**。
>
> **前提**:
> - 已 `git pull` 最新代码(包含本任务所有改动)
> - 本地 `mvn` 已就绪,Java 17+
> - 本地 `trade-service` 跑得通(连得上 PG / Nacos)
> - 一台能上网的 Windows / Mac / Linux 都行

---

## 13. 接入步骤(7 步走完)

### Step 1:打开支付宝开放平台沙箱后台(2 分钟)

1. 浏览器打开 https://open.alipay.com/develop/sandbox/app
2. 用**任意支付宝账号**扫码登录(个人账号即可,不需要企业认证)
3. 登录后会看到沙箱应用页,系统**自动分配**一个沙箱应用,长这样:

```
┌──────────────────────────────────────────────────────┐
│  沙箱应用                                            │
│  ─────────────                                       │
│  APPID:  2021000123456789                            │
│  支付宝网关:  https://openapi.alipaydev.com/gateway.do │
└──────────────────────────────────────────────────────┘
```

4. **复制 APPID**,待会儿要用

> 沙箱环境**无需单独申请**,每个支付宝账号自动拥有。**不要**用正式应用的 APPID。

---

### Step 2:生成 RSA2 密钥对(3 分钟)

1. 下载官方"支付宝签名验签工具":
   - 官方下载页:https://opendocs.alipay.com/common/02kipk
   - 选 `Windows` 或 `Mac` 版,解压即用(Java 写的双击 jar 即可)

2. 打开工具,选 **"生成密钥"**:
   - **密钥格式**:`PKCS8` ← **重要!Java 必须用 PKCS8**
   - **密钥长度**:2048
   - **算法**:`RSA2`

3. 点 **"生成密钥"**,会得到两段:

```
应用私钥 (商户自己保存,放进 .env):
MIIEvQIBADANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxxxxxxxxxx
... (约 1700 字符)

应用公钥 (提交到沙箱后台):
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxxxxxxxxxx
... (约 400 字符)
```

4. **私钥**:完整复制(包括所有换行,粘贴到 `.env` 时整段粘,**不要带 `-----BEGIN/END-----` 头尾**)
5. **公钥**:完整复制,下一步要贴到沙箱后台

> 工具栏里有个"复制"按钮一键复制,避免漏字符。

> **关于 RSA2 vs SM2(国密)的选择**:
> 官方签名验签工具里会看到"算法"一栏有 **RSA2** 和 **SM2** 两个选项——这里**必须选 RSA2**。
>
> - **RSA2** = SHA256 + 2048 位 RSA,沙箱**自助配置**,EasySDK 直接支持,99% 商业场景都用这个
> - **SM2** = 国密 GM/T 0003,沙箱**没有自助上传入口**,且 EasySDK 默认只支持 RSA2;SM2 是给银行/政企上线合规阶段用的,需要联系支付宝技术支持开通 + 切到 alipay-sdk-java 证书模式 + 引入 BouncyCastle
>
> 本项目当前 **MVP 阶段统一用 RSA2**,SM2 留到上线合规阶段再单独 PR 切证书模式。

---

### Step 3:把"应用公钥"提交到沙箱,拿回"支付宝公钥"(2 分钟)

1. 回到 https://open.alipay.com/develop/sandbox/app
2. 找到 **"应用公钥"** 文本框,粘贴 Step 2 复制的"应用公钥"
3. 点 **"保存设置"** → 系统会自动生成一段"**支付宝公钥**",显示在下方:

```
┌──────────────────────────────────────────────┐
│  支付宝公钥(用于验签)                       │
│  ────────────────────────                     │
│  MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCg...   │
│  ...                                          │
└──────────────────────────────────────────────┘
```

4. **复制"支付宝公钥"** → 这才是要配到 `.env` 的 `ALIPAY_ALIPAY_PUBLIC_KEY`!
5. ⚠️ **易错点**:验签用的是"**支付宝公钥**",**不是**"应用公钥"。两者长得像,但不能混。

---

### Step 4:安装内网穿透工具(5 分钟)

> 目的:把本机 `localhost:8083` 暴露成一个公网 HTTPS 域名,让支付宝能回调。

**方案 A(推荐,稳定):cloudflared 命名隧道 + 自购域名**

1. 买一个便宜域名(.xyz / .top 等,约 ¥10/年,Namesilo / 阿里云万网均可)
2. 把域名的 NS 改到 Cloudflare(注册 Cloudflare 账号 → Add Site → 按提示改 NS)
3. 安装 cloudflared:

   ```bash
   # Windows (winget)
   winget install --id Cloudflare.cloudflared

   # Mac
   brew install cloudflared

   # Linux
   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
   chmod +x /usr/local/bin/cloudflared
   ```

4. 登录 + 创建命名隧道:

   ```bash
   cloudflared tunnel login        # 弹浏览器授权
   cloudflared tunnel create alipay-dev
   ```

5. 配置 `~/.cloudflared/config.yml`:

   ```yaml
   tunnel: <你的隧道 UUID>
   credentials-file: <UUID>.json
   ingress:
     - hostname: pay-dev.yourdomain.xyz   # 你买的域名
       service: http://localhost:8083      # trade-service 端口
     - service: http_status:404
   ```

6. 加 DNS 记录:

   ```bash
   cloudflared tunnel route dns alipay-dev pay-dev.yourdomain.xyz
   ```

7. 启动(保持这个窗口别关):

   ```bash
   cloudflared tunnel run alipay-dev
   ```

   启动后你能看到一个 `https://pay-dev.yourdomain.xyz` 的 HTTPS 域名,自动证书。

**方案 B(临时凑合):cpolar**

```bash
# 1. https://www.cpolar.com/ 注册账号,下载客户端
# 2. 启动(免费版域名会变,适合一次性调试)
cpolar http 8083
# 输出类似:https://abc123.cpolar.cn -> http://localhost:8083
```

---

### Step 5:在沙箱后台配授权回调地址(1 分钟)

1. 回到 https://open.alipay.com/develop/sandbox/app
2. 找 **"应用配置"** → **"接口加签方式/授权回调地址"** 一栏
3. 填穿透出来的域名 + `/api/trade/alipay/notify` 路径(网关 StripPrefix=2 后实际是 `/alipay/notify`,但配的时候要带完整路径前缀 `/api/trade`)

   ```
   https://pay-dev.yourdomain.xyz/api/trade/alipay/notify
   ```

4. 保存

> **注意**:
> - 路径**必须**是 `/api/trade/alipay/notify`(经 gateway 转发后变成 `/alipay/notify` 命中白名单)
> - 如果直接调 `localhost:8083/alipay/notify`,配这个地址也行——但**不推荐**,失去了"穿透"的意义

---

### Step 6:改本地配置(3 分钟)

打开 `services/trade-service/src/main/resources/application.yml`,把 `alipay:` 段改成:

```yaml
alipay:
  enabled: ${ALIPAY_ENABLED:true}              # 关键:从 false 改成 true
  app-id: ${ALIPAY_APP_ID:2021000123456789}   # 替换成 Step 1 拿到的 APPID
  app-private-key: ${ALIPAY_APP_PRIVATE_KEY:粘贴 Step 2 私钥}
  alipay-public-key: ${ALIPAY_ALIPAY_PUBLIC_KEY:粘贴 Step 3 支付宝公钥}
  gateway-url: ${ALIPAY_GATEWAY:https://openapi-sandbox.dl.alipaydev.com/gateway.do}
  protocol: https
  sign-type: RSA2
  charset: UTF-8
  notify-url: ${ALIPAY_NOTIFY_URL:https://pay-dev.yourdomain.xyz/api/trade/alipay/notify}
  return-url: ${ALIPAY_RETURN_URL:https://pay-dev.yourdomain.xyz/api/trade/alipay/return}
```

或者更推荐用环境变量(不污染 yml):

```bash
# ~/.bashrc 或启动脚本里 export
export ALIPAY_ENABLED=true
export ALIPAY_APP_ID=2021000123456789
export ALIPAY_APP_PRIVATE_KEY="$(cat ~/alipay_private_key.pem)"   # 私钥整段
export ALIPAY_ALIPAY_PUBLIC_KEY="$(cat ~/alipay_public_key.pem)"  # 支付宝公钥
export ALIPAY_GATEWAY=https://openapi.alipaydev.com/gateway.do
export ALIPAY_NOTIFY_URL=https://pay-dev.yourdomain.xyz/api/trade/alipay/notify
export ALIPAY_RETURN_URL=https://pay-dev.yourdomain.xyz/api/trade/alipay/return
```

---

### Step 7:启动 + 端到端走一遍(5 分钟)

#### 7.1 启动 trade-service

```bash
cd d:/dev/project/py/welove-shop-agt
mvn -pl services/trade-service -am spring-boot:run
```

看到这条日志就说明 OK:

```
[alipay] easysdk initialized, gateway=openapi.alipaydev.com, appId=2021000123456789
```

如果没看到 → 走的是模拟支付路径,检查 `ALIPAY_ENABLED` 是否真的为 `true`。

#### 7.2 拿 JWT

```bash
# 登录拿 token
curl -X POST http://localhost:8080/api/user/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"Test123456"}'
```

返回里取 `data.token`。

#### 7.3 下单

```bash
TOKEN="上面拿到的 token"
curl -X POST http://localhost:8080/api/trade/order/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "addressId": 1,
    "items": [{"productId": 1001, "skuId": 2001, "quantity": 1}]
  }'
```

返回里取 `data.id`(= orderId)。

#### 7.4 发起支付 ⭐

```bash
curl -X POST http://localhost:8080/api/trade/alipay/create/$ORDER_ID \
  -H "Authorization: Bearer $TOKEN"
```

会返回一段 HTML form,内容形如:

```html
<form id="alipaysubmit" name="alipaysubmit" action="https://openapi.alipaydev.com/gateway.do?..." method="POST">
  <input type="hidden" name="biz_content" value="..."/>
  ...
</form>
<script>document.forms['alipaysubmit'].submit();</script>
```

**把这段 HTML 存到本地 `pay.html`,浏览器打开 → 自动跳到沙箱收银台**。

#### 7.5 用沙箱账号付款

1. 沙箱收银台会让你选"登录账号"和"支付密码"
2. 拿沙箱买家账号:打开 https://open.alipay.com/develop/sandbox/account
3. 复制"买家账号"和"支付密码"(默认 `111111`)
4. 在收银台里输入 → 点"确认付款" → 看到"支付成功"页面

> 收银台可能让你"扫码",沙箱 APP 在这里:https://opendocs.alipay.com/support/01razc(安卓 / iOS 测试版)

#### 7.6 查订单状态

```bash
curl http://localhost:8080/api/trade/alipay/status/$ORDER_ID \
  -H "Authorization: Bearer $TOKEN"
```

期望返回:

```json
{
  "code": 0,
  "data": {
    "orderNo": "20260720120000123456",
    "orderStatus": 1,              ← 关键:从 0 变成 1
    "tradeNo": "2026072022001...", ← 支付宝交易号
    "tradeStatus": "TRADE_SUCCESS",
    "payAmount": 0.01,
    "payChannel": "ALIPAY_SANDBOX" ← 关键:从 MOCK 变成 ALIPAY_SANDBOX
  }
}
```

#### 7.7 看后端日志

trade-service 控制台应该打出:

```
[alipay-notify] order paid, orderNo=20260720..., tradeNo=20260720...
[order-callback] order paid, orderNo=20260720..., tradeNo=..., channel=ALIPAY_SANDBOX
```

**两条日志都出现 → 接入成功! 🎉**

---

## 14. 常见问题(FAQ)

### Q1:启动后没看到 `[alipay] easysdk initialized` 日志

**原因**:`alipay.enabled` 没生效,默认还是 `false`。

**解决**:
1. 检查环境变量:`echo $ALIPAY_ENABLED` 应输出 `true`
2. 或检查 `application.yml` 里 `alipay.enabled` 的值
3. 或在 IDE Run Configuration 里加 `ALIPAY_ENABLED=true`

---

### Q2:点击支付后,沙箱收银台提示"系统繁忙"或"参数错误"

**大概率原因**:私钥或公钥配错了。

**排查顺序**:
1. 看日志里有没有 `rsaCheck failed` 或 `签名错误`
2. 确认 `ALIPAY_APP_PRIVATE_KEY` 是**应用私钥**(Step 2 那段)
3. 确认 `ALIPAY_ALIPAY_PUBLIC_KEY` 是**支付宝公钥**(Step 3 拿到的那段,**不是**应用公钥)
4. 确认两个密钥是**同一对**(同一份密钥对生成的)
5. 确认私钥**无** `-----BEGIN PRIVATE KEY-----` 头尾

**快速验证脚本**(Java,放在 `PaymentServiceImpl.init()` 启动后调用):

```java
System.out.println("priv start: " + alipayProperties.getAppPrivateKey().substring(0, 30));
System.out.println("pub  start: " + alipayProperties.getAlipayPublicKey().substring(0, 30));
```

如果 `priv` 是 `MIIEvQIBADANBgkqhkiG9w0BAQ...` → 私钥格式 OK
如果 `pub` 是 `MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ...` → 公钥格式 OK

---

### Q3:支付成功,但订单状态没变 / 一直显示"待付款"

**大概率原因**:异步通知没收到 / 验签失败 / 通知路径走错。

**排查顺序**:
1. **看 trade-service 日志有没有 `[alipay-notify]` 相关输出**:
   - 没有 → 通知根本没进来,检查穿透域名 + 沙箱后台"授权回调地址"
   - 有 `signature verification failed` → 公钥配错,回 Q2
   - 有 `order not found` → 订单号对不上,检查 `out_trade_no` 是否用 `order_no`
   - 有 `amount mismatch` → 金额不一致,检查 `pay_amount` 字段计算
   - 有 `already processed` → 重复通知,无害

2. **测试通知是否进得来**:
   ```bash
   # 模拟一笔通知(注意:验签会失败,但能确认路径通)
   curl -X POST https://pay-dev.yourdomain.xyz/api/trade/alipay/notify \
     -d "out_trade_no=test" \
     -d "trade_status=TRADE_SUCCESS"
   ```
   期望看到 trade-service 日志: `[alipay-notify] verifyNotify threw` 或 `signature verification failed`(说明路径通,只是签名问题)

3. **检查沙箱后台的"通知记录"**(沙箱应用页 → 通知查询):
   - 状态是"已送达"→ 通知发出去了,问题在后端
   - 状态是"未送达"→ 网络问题,检查穿透是否还活着

---

### Q4:前端拿到 form HTML 不知道怎么用

```html
<!-- 错误做法:直接显示 HTML 源码 -->
<pre>{{ html }}</pre>

<!-- 正确做法:用 v-html / innerHTML 渲染,浏览器会自动执行 script 提交 -->
<div v-html="payForm"></div>

<!-- 或用 fetch + 后端跳转:
     后端可以直接 302 重定向到沙箱,前端不需要处理 form
     (本期没做,可作为后续优化)
-->
```

---

### Q5:本地用 `ALIPAY_ENABLED=false` 跑通,切到 `true` 就报错

**可能原因**:`app-private-key` 配了带换行/头尾的格式。

**解决**:
```bash
# 看私钥实际值
echo "$ALIPAY_APP_PRIVATE_KEY" | head -2
# 应该是一整行 MIIEvQI... 没有 -----BEGIN PRIVATE KEY-----
# 如果有头尾,用 sed 去掉
export ALIPAY_APP_PRIVATE_KEY=$(echo "$ALIPAY_APP_PRIVATE_KEY" | sed 's/-----.*-----//g' | tr -d '\n')
```

---

### Q6:穿透域名 HTTPS 证书无效

**现象**:浏览器报 `NET::ERR_CERT_AUTHORITY_INVALID`

**解决**:
- cloudflared:这是 Cloudflare 自动签发的证书,应该没问题。如果出问题,确认域名 NS 真的在 Cloudflare(在 Cloudflare DNS 页能看到)
- cpolar:免费版可能用自签证书,需要手动信任。**生产不要用自签证书**

---

### Q7:沙箱收银台点了"付款"一直转圈

**可能原因**:沙箱 APP 没装,导致扫码环节卡住。

**解决**:
- 用**账号密码登录**(收银台里通常有"账号登录"tab,而不是扫码)
- 或装沙箱 APP:https://opendocs.alipay.com/support/01razc

---

## 15. 验收 checklist(提交 PR 前自查)

> 把这一节当 checklist 用,每条都打勾才能合并。

### 15.1 配置正确

- [ ] `ALIPAY_ENABLED=true`(或 yml 显式开启)
- [ ] `ALIPAY_APP_ID` 是沙箱 APPID(以 `2021` 开头)
- [ ] `ALIPAY_APP_PRIVATE_KEY` 是 PKCS8 私钥,**无** `-----BEGIN/END-----` 头尾
- [ ] `ALIPAY_ALIPAY_PUBLIC_KEY` 是**支付宝公钥**(不是应用公钥)
- [ ] `ALIPAY_GATEWAY=https://openapi.alipaydev.com/gateway.do`
- [ ] `ALIPAY_NOTIFY_URL` 指向穿透出来的公网 HTTPS + `/api/trade/alipay/notify`
- [ ] 沙箱后台"授权回调地址"和 `ALIPAY_NOTIFY_URL` 一致

### 15.2 代码改动完整

- [ ] `services/trade-service/pom.xml` 加了 `alipay-easysdk 2.2.2` 依赖
- [ ] `services/trade-service/src/main/resources/db/migration/V2__add_payment_columns_to_orders.sql` 存在
- [ ] `services/trade-service/src/main/java/com/welove/shop/trade/config/AlipayProperties.java` 存在
- [ ] `services/trade-service/src/main/java/com/welove/shop/trade/config/AlipayConfig.java` 存在
- [ ] `services/trade-service/src/main/java/com/welove/shop/trade/service/PaymentService.java` 存在
- [ ] `services/trade-service/src/main/java/com/welove/shop/trade/service/impl/PaymentServiceImpl.java` 存在
- [ ] `services/trade-service/src/main/java/com/welove/shop/trade/controller/AlipayController.java` 存在
- [ ] `services/trade-service/src/main/java/com/welove/shop/trade/controller/AlipayNotifyController.java` 存在
- [ ] `Order.java` 加了 `payChannel` / `tradeNo` 字段
- [ ] `TradeErrorCode.java` 加了 403xx 错误码
- [ ] `WebMvcConfig.java` 白名单加了 `/alipay/notify` + `/alipay/return`
- [ ] `OrderService.java` 加了 `markPaidByCallback` 方法
- [ ] `OrderServiceImpl.java` 实现了 `markPaidByCallback`(含金额校验 + 幂等)

### 15.3 编译/启动通过

- [ ] `mvn -pl services/trade-service -am clean compile -DskipTests` 输出 `BUILD SUCCESS`
- [ ] 启动日志有 `[alipay] easysdk initialized, gateway=openapi.alipaydev.com, appId=...`
- [ ] `curl http://localhost:8083/actuator/health` 返回 200

### 15.4 端到端流程通过(必须实跑一次)

- [ ] `POST /api/trade/order/create` 能创建订单,返回 `orderId`
- [ ] `POST /api/trade/alipay/create/{orderId}` 返回带 `<form>` 的 HTML
- [ ] 浏览器打开 form HTML 自动跳到 `openapi.alipaydev.com` 沙箱收银台
- [ ] 用沙箱账号(`xxx@sandbox.com` / `111111`)登录付款 → 显示"支付成功"
- [ ] 浏览器自动跳到穿透域名的 `/api/trade/alipay/return`
- [ ] `GET /api/trade/alipay/status/{orderId}` 返回 `orderStatus=1, payChannel=ALIPAY_SANDBOX, tradeStatus=TRADE_SUCCESS`
- [ ] 数据库查 `orders` 表:`status=1, pay_channel='ALIPAY_SANDBOX', trade_no='...'`
- [ ] trade-service 控制台有 `[alipay-notify] order paid, orderNo=...` 日志

### 15.5 降级路径不破坏

- [ ] 把 `ALIPAY_ENABLED` 改回 `false`,重启 trade-service
- [ ] `POST /api/trade/alipay/create/{orderId}` 返回"模拟支付成功"HTML
- [ ] 数据库订单直接 0 → 1,`pay_channel='MOCK'`
- [ ] 业务主流程不受影响

### 15.6 文档/约定

- [ ] 本文档 `docs/plan/alipay-sandbox-payment.md` 已随代码提交
- [ ] PR 描述里写明:**"需要在沙箱后台配置授权回调地址"**(给运维/接手的人看)
- [ ] 未把真实 APPID/密钥提交到 git(应只在 `.env` 或部署配置里)

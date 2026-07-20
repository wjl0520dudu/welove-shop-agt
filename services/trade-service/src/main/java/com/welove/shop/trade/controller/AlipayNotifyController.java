package com.welove.shop.trade.controller;

import com.welove.shop.trade.config.AlipayProperties;
import com.welove.shop.trade.service.OrderService;
import com.welove.shop.trade.service.PaymentService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * 支付宝回调端点。
 * <p>
 * 路径必须留在 {@code WebMvcConfig.WHITELIST} 免鉴权(见 application 注解):
 * <ul>
 *   <li>{@code POST /alipay/notify} — 异步通知(支付宝服务器 POST)</li>
 *   <li>{@code GET /alipay/return} — 同步跳转(浏览器 GET)</li>
 * </ul>
 * <b>异步通知响应规则</b>:必须返回纯字符串 {@code "success"} 或 {@code "fail"},
 * 不能含任何 HTML/JSON/换行/BOM,否则支付宝会持续重试(最长 48h)。
 * <p>
 * <b>同步跳转</b>:支付宝浏览器 GET 到 {@code /alipay/return},后端从 query 里拿
 * {@code out_trade_no},查到 orderId 后 302 到前端 H5 支付结果页
 * ({@code alipay.h5-return-url} + ?orderId=xxx)。前端拿 orderId 轮询
 * {@code /alipay/status/{orderId}} 拿到最终支付状态。
 */
@Slf4j
@RestController
@RequestMapping("/alipay")
@RequiredArgsConstructor
public class AlipayNotifyController {

    private final PaymentService paymentService;
    private final OrderService orderService;
    private final AlipayProperties alipayProperties;

    /**
     * 异步通知 — 业务逻辑必须在这里完成,不能依赖 return_url。
     * <p>
     * 验签和金额校验都在 {@link PaymentService#handlePayNotify} 内部完成。
     */
    @PostMapping("/notify")
    public String notify(HttpServletRequest request) {
        Map<String, String> params = new HashMap<>();
        request.getParameterMap().forEach((k, v) -> {
            // sign / sign_type 不参与业务参数,但 EasySDK 的 verifyNotify 会自动剔除
            if (v != null && v.length > 0) {
                params.put(k, v[0]);
            }
        });
        try {
            paymentService.handlePayNotify(params);
            return "success";
        } catch (Exception e) {
            log.error("[alipay-notify] handle error, params={}", params.keySet(), e);
            return "fail";
        }
    }

    /**
     * 同步跳转 — 仅做页面展示,业务逻辑以 notify_url 为准。
     * <p>
     * 行为:
     * <ol>
     *   <li>从 query 取 {@code out_trade_no}(支付宝同步跳转时会带)</li>
     *   <li>按 orderNo 查 orderId</li>
     *   <li>如果配置了 {@code alipay.h5-return-url},302 跳到前端支付结果页(带 orderId)</li>
     *   <li>否则降级返回 "支付完成,请回到订单列表查看状态"</li>
     * </ol>
     */
    @GetMapping("/return")
    public void returnUrl(HttpServletRequest request, HttpServletResponse response) throws IOException {
        String outTradeNo = request.getParameter("out_trade_no");
        Long orderId = outTradeNo != null ? orderService.findIdByOrderNo(outTradeNo) : null;

        String h5Url = alipayProperties.getH5ReturnUrl();
        if (StringUtils.hasText(h5Url) && orderId != null) {
            // 当前类是 @RestController,返回 "redirect:..." 只会被当成普通文本。
            // 必须显式发送 302,否则支付宝回跳后页面会停留在这段字符串上。
            String separator = h5Url.contains("?") ? "&" : "?";
            String encodedId = URLEncoder.encode(String.valueOf(orderId), StandardCharsets.UTF_8);
            response.sendRedirect(h5Url + separator + "orderId=" + encodedId);
            return;
        }

        log.warn("[alipay-return] no h5-return-url configured or orderNo {} not found, fallback plain text",
                outTradeNo);
        response.setContentType("text/plain;charset=UTF-8");
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.getWriter().write("支付完成,请回到订单列表查看状态");
    }
}

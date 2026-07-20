package com.welove.shop.trade.controller;

import com.welove.shop.common.core.result.Result;
import com.welove.shop.common.security.context.UserContext;
import com.welove.shop.trade.dto.PayStatusVO;
import com.welove.shop.trade.service.PaymentService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 支付宝用户端接口。
 * <p>
 * 前端流程:
 * <ol>
 *   <li>用户点击"去支付" → {@code POST /alipay/create/{orderId}} 拿 H5 form HTML</li>
 *   <li>前端原生提交 form → 跳支付宝 H5 收银台</li>
 *   <li>用户付款后浏览器跳 {@code /alipay/return} → 前端开始轮询 status</li>
 *   <li>{@code GET /alipay/status/{orderId}} 看到 orderStatus=1 即视为成功</li>
 * </ol>
 * 异步通知由 {@link AlipayNotifyController} 接管,业务逻辑在那里完成。
 */
@RestController
@RequestMapping("/alipay")
@RequiredArgsConstructor
public class AlipayController {

    private final PaymentService paymentService;

    /**
     * 发起支付宝网页支付 — 默认是 H5 WAP,可通过 alipay.pay-mode=page 切回 PC。
     * <p>
     * 沙箱未启用(alipay.enabled=false)时,服务端直接 0 → 1,返回一段"模拟支付成功"
     * 的 HTML 提示,便于本地无配置时跑通。
     */
    @PostMapping(value = "/create/{orderId}", produces = "text/html;charset=UTF-8")
    public String create(@PathVariable Long orderId) {
        return paymentService.createPayPage(UserContext.requireUserId(), orderId);
    }

    /**
     * 查询支付状态 — 前端轮询用,沙箱启用时主动调支付宝 query。
     */
    @GetMapping("/status/{orderId}")
    public Result<PayStatusVO> status(@PathVariable Long orderId) {
        return Result.ok(paymentService.queryTradeStatus(UserContext.requireUserId(), orderId));
    }

    /**
     * 主动关闭未支付订单(用户取消支付时)。
     */
    @PostMapping("/close/{orderId}")
    public Result<Void> close(@PathVariable Long orderId) {
        paymentService.closePay(UserContext.requireUserId(), orderId);
        return Result.ok();
    }
}

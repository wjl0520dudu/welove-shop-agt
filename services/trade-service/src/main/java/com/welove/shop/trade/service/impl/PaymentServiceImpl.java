package com.welove.shop.trade.service.impl;

import com.alipay.easysdk.factory.Factory;
import com.alipay.easysdk.payment.common.models.AlipayTradeCloseResponse;
import com.alipay.easysdk.payment.common.models.AlipayTradeQueryResponse;
import com.alipay.easysdk.payment.page.models.AlipayTradePagePayResponse;
import com.alipay.easysdk.payment.wap.models.AlipayTradeWapPayResponse;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.welove.shop.common.core.exception.BizException;
import com.welove.shop.trade.config.AlipayProperties;
import com.welove.shop.trade.dto.PayStatusVO;
import com.welove.shop.trade.entity.Order;
import com.welove.shop.trade.exception.TradeErrorCode;
import com.welove.shop.trade.mapper.OrderMapper;
import com.welove.shop.trade.service.OrderService;
import com.welove.shop.trade.service.PaymentService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * 支付服务实现。
 * <p>
 * 分两条路径:
 * <ul>
 *   <li><b>沙箱启用</b>(alipay.enabled=true):走 EasySDK 调支付宝</li>
 *   <li><b>沙箱未启用</b>(默认):走"模拟支付"降级,本地无任何外部依赖即可跑通</li>
 * </ul>
 * 业务侧不感知差异,Controller / Frontend 看到的接口形态一致。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PaymentServiceImpl implements PaymentService {

    private final OrderMapper orderMapper;
    private final OrderService orderService;
    private final AlipayProperties alipayProperties;

    @Override
    public String createPayPage(Long userId, Long orderId) {
        Order order = requireOwnedOrder(userId, orderId);
        if (order.getStatus() != 0) {
            throw new BizException(TradeErrorCode.ORDER_STATUS_INVALID, "订单状态不允许支付");
        }

        if (!alipayProperties.isEnabled()) {
            // 降级:模拟支付,直接走 markPaidByCallback 完成 0 → 1
            log.info("[pay-mock] enabled=false, skip alipay, directly mark paid. orderNo={}",
                    order.getOrderNo());
            orderService.markPaidByCallback(
                    order.getOrderNo(),
                    "MOCK-" + order.getOrderNo(),
                    order.getPayAmount().toPlainString(),
                    "MOCK");
            return buildMockPayPage(order);
        }

        try {
            String subject = buildSubject(order);
            String orderNo = order.getOrderNo();
            String amount = order.getPayAmount().toPlainString();

            if ("page".equalsIgnoreCase(alipayProperties.getPayMode())) {
                AlipayTradePagePayResponse resp = Factory.Payment.Page()
                        .asyncNotify(alipayProperties.getNotifyUrl())
                        .pay(subject, orderNo, amount, alipayProperties.getReturnUrl());
                return resp.getBody();
            }

            AlipayTradeWapPayResponse resp = Factory.Payment.Wap()
                    .asyncNotify(alipayProperties.getNotifyUrl())
                    .pay(subject, orderNo, amount,
                            alipayProperties.getQuitUrl(),
                            alipayProperties.getReturnUrl());
            return resp.getBody();
        } catch (Exception e) {
            log.error("[alipay] createPayPage failed, orderNo={}", order.getOrderNo(), e);
            throw new BizException(TradeErrorCode.PAY_CREATE_FAILED,
                    "创建支付单失败:" + e.getMessage());
        }
    }

    @Override
    @Transactional
    public void handlePayNotify(Map<String, String> params) {
        if (!alipayProperties.isEnabled()) {
            // 沙箱未启用时不应收到通知;若收到,记日志返回成功避免重试
            log.warn("[alipay-notify] received but alipay disabled, params={}", params.keySet());
            return;
        }

        // 验签(EasySDK 内部用 Config.alipayPublicKey,工厂模式无需手动传公钥)
        Boolean verified;
        try {
            verified = Factory.Payment.Common().verifyNotify(params);
        } catch (Exception e) {
            log.error("[alipay-notify] verifyNotify threw", e);
            throw new BizException(TradeErrorCode.PAY_NOTIFY_INVALID, "验签异常:" + e.getMessage());
        }
        if (!Boolean.TRUE.equals(verified)) {
            log.warn("[alipay-notify] signature verification failed, params={}", params);
            throw new BizException(TradeErrorCode.PAY_NOTIFY_INVALID, "签名校验失败");
        }

        String outTradeNo = params.get("out_trade_no");
        String tradeNo = params.get("trade_no");
        String tradeStatus = params.get("trade_status");
        String totalAmount = params.get("total_amount");

        if (outTradeNo == null) {
            throw new BizException(TradeErrorCode.PAY_NOTIFY_INVALID, "out_trade_no 缺失");
        }

        Order order = orderMapper.selectOne(
                new LambdaQueryWrapper<Order>().eq(Order::getOrderNo, outTradeNo));
        if (order == null) {
            log.warn("[alipay-notify] order not found, orderNo={}", outTradeNo);
            throw new BizException(TradeErrorCode.ORDER_NOT_FOUND, "订单不存在:" + outTradeNo);
        }

        if ("TRADE_SUCCESS".equals(tradeStatus) || "TRADE_FINISHED".equals(tradeStatus)) {
            // 复用 OrderService 的幂等方法
            orderService.markPaidByCallback(outTradeNo, tradeNo, totalAmount, "ALIPAY_SANDBOX");
        } else if ("TRADE_CLOSED".equals(tradeStatus)) {
            // 支付宝侧已关闭(超时未付),本地也置 4
            if (order.getStatus() == 0) {
                order.setStatus(4);
                order.setUpdateTime(LocalDateTime.now());
                order.setTradeNo(tradeNo);
                orderMapper.updateById(order);
                log.info("[alipay-notify] order closed, orderNo={}", outTradeNo);
            }
        } else {
            log.info("[alipay-notify] status={} not handled, orderNo={}", tradeStatus, outTradeNo);
        }
    }

    @Override
    public PayStatusVO queryTradeStatus(Long userId, Long orderId) {
        Order order = requireOwnedOrder(userId, orderId);
        PayStatusVO vo = new PayStatusVO();
        vo.setOrderNo(order.getOrderNo());
        vo.setOrderStatus(order.getStatus());
        vo.setTradeNo(order.getTradeNo());
        vo.setPayAmount(order.getPayAmount());
        vo.setPayChannel(order.getPayChannel());

        // 沙箱启用时,主动调支付宝 query 拿最新 tradeStatus(用于对账 / 前端轮询)
        if (alipayProperties.isEnabled() && order.getStatus() == 0) {
            try {
                AlipayTradeQueryResponse resp = Factory.Payment.Common()
                        .query(order.getOrderNo());
                if (resp != null && "10000".equals(resp.code)) {
                    vo.setTradeStatus(resp.tradeStatus);
                    if (("TRADE_SUCCESS".equals(resp.tradeStatus)
                            || "TRADE_FINISHED".equals(resp.tradeStatus))
                            && order.getStatus() == 0) {
                        // notify 可能因公网回调暂时不可达而延迟;主动 query 仍是
                        // 支付宝可信结果,复用金额校验 + 幂等更新避免结果页一直转圈。
                        orderService.markPaidByCallback(
                                order.getOrderNo(),
                                resp.tradeNo,
                                resp.totalAmount,
                                "ALIPAY_SANDBOX");
                        vo.setOrderStatus(1);
                        vo.setTradeNo(resp.tradeNo);
                        vo.setPayChannel("ALIPAY_SANDBOX");
                    }
                }
            } catch (Exception e) {
                log.warn("[alipay-query] failed, orderNo={}, err={}", order.getOrderNo(), e.getMessage());
            }
        }
        return vo;
    }

    @Override
    @Transactional
    public void closePay(Long userId, Long orderId) {
        Order order = requireOwnedOrder(userId, orderId);
        if (order.getStatus() != 0) {
            throw new BizException(TradeErrorCode.ORDER_STATUS_INVALID, "仅未支付订单可关闭");
        }

        if (alipayProperties.isEnabled()) {
            try {
                AlipayTradeCloseResponse resp = Factory.Payment.Common()
                        .close(order.getOrderNo());
                if (resp != null && !"10000".equals(resp.code)) {
                    log.warn("[alipay-close] not 10000, orderNo={}, code={}, msg={}",
                            order.getOrderNo(), resp.code, resp.msg);
                }
            } catch (Exception e) {
                log.error("[alipay-close] failed, orderNo={}", order.getOrderNo(), e);
                throw new BizException(TradeErrorCode.PAY_CLOSE_FAILED, "关闭失败:" + e.getMessage());
            }
        }
        // 本地 0 → 4
        order.setStatus(4);
        order.setUpdateTime(LocalDateTime.now());
        orderMapper.updateById(order);
    }

    // ---------- 内部 ----------

    private Order requireOwnedOrder(Long userId, Long orderId) {
        Order order = orderMapper.selectById(orderId);
        if (order == null || !order.getUserId().equals(userId)) {
            throw new BizException(TradeErrorCode.ORDER_NOT_FOUND, "订单不存在");
        }
        return order;
    }

    private String buildSubject(Order order) {
        return "WeLove Shop 订单 " + order.getOrderNo();
    }

    /**
     * 测试环境模拟支付也返回一个可提交的 form,保持与真实支付宝页面相同的前端链路。
     * <p>
     * 前端会复制并提交这个 GET form 到 H5 结果页,结果页随后查询到本地已经置为已支付的订单。
     */
    private String buildMockPayPage(Order order) {
        String h5Url = alipayProperties.getH5ReturnUrl();
        if (!StringUtils.hasText(h5Url)) {
            return "<!doctype html><html><body><h3>模拟支付成功</h3>"
                    + "<p>订单 " + order.getOrderNo() + " 已直接置为已支付。</p>"
                    + "</body></html>";
        }

        String separator = h5Url.contains("?") ? "&" : "?";
        String returnUrl = h5Url + separator + "orderId=" + order.getId();
        String escapedUrl = org.springframework.web.util.HtmlUtils.htmlEscape(returnUrl);
        return "<!doctype html><html><body>"
                + "<form id=\"mockAlipaySubmit\" method=\"GET\" action=\""
                + escapedUrl + "\"></form>"
                + "</body></html>";
    }
}

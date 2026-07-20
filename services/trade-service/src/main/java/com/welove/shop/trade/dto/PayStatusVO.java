package com.welove.shop.trade.dto;

import lombok.Data;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;

/**
 * 支付状态 VO(用于前端轮询查询 / 主动对账)。
 * <p>
 * 暴露最小集:订单号、本地订单状态、支付宝交易号、交易状态、金额。
 */
@Data
public class PayStatusVO implements Serializable {

    @Serial
    private static final long serialVersionUID = 1L;

    /** 本地订单号。 */
    private String orderNo;

    /** 本地订单状态:0 待付款 / 1 待发货 / 2 待收货 / 3 已完成 / 4 已取消。 */
    private Integer orderStatus;

    /** 支付宝交易号(未支付时为 null)。 */
    private String tradeNo;

    /** 支付宝交易状态:WAIT_BUYER_PAY / TRADE_CLOSED / TRADE_SUCCESS / TRADE_FINISHED。 */
    private String tradeStatus;

    /** 支付金额(冗余字段,便于前端展示)。 */
    private BigDecimal payAmount;

    /** 支付渠道:MOCK / ALIPAY_SANDBOX。 */
    private String payChannel;
}

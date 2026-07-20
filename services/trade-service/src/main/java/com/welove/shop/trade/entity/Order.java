package com.welove.shop.trade.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 订单主表实体。
 * <p>
 * 表名 {@code orders}(order 是 SQL 保留字,统一改成 orders)。
 * <p>
 * status 状态机:
 * <ul>
 *   <li>0 = 待付款</li>
 *   <li>1 = 待发货</li>
 *   <li>2 = 待收货</li>
 *   <li>3 = 已完成</li>
 *   <li>4 = 已取消</li>
 * </ul>
 */
@Data
@TableName("orders")
public class Order implements Serializable {

    @Serial
    private static final long serialVersionUID = 1L;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    /** 订单号:yyyyMMddHHmmss + 6 位随机,全局唯一。 */
    private String orderNo;

    /** 状态,见类注释。 */
    private Integer status;

    private BigDecimal totalAmount;

    private BigDecimal payAmount;

    private BigDecimal freightAmount;

    /** 关联 user_svc.address.id(跨服务字段,不加 FK)。 */
    private Long addressId;

    private String receiverName;

    private String receiverPhone;

    /** 收货地址快照:省市区+详细拼接。 */
    private String receiverAddress;

    private String remark;

    private LocalDateTime createTime;

    private LocalDateTime payTime;

    private LocalDateTime deliveryTime;

    private LocalDateTime receiveTime;

    private LocalDateTime updateTime;

    /** 支付渠道:MOCK(模拟)/ALIPAY_SANDBOX(支付宝沙箱)/未来加 WECHAT/ALIPAY_PROD 等。 */
    private String payChannel;

    /** 支付宝交易号(异步通知里回传)。 */
    private String tradeNo;
}

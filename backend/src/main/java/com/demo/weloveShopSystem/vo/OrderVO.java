package com.demo.weloveShopSystem.vo;

import lombok.Data;
import java.math.BigDecimal;
import com.demo.weloveShopSystem.entity.OrderItem;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 订单接口返回视图对象，包含订单主信息和订单明细。
 */
@Data
public class OrderVO {
    /** 订单 ID。 */
    private Long id;
    /** 订单编号。 */
    private String orderNo;
    /** 用户 ID。 */
    private Long userId;
    /** 订单状态。 */
    private Integer status;
    /** 订单总金额。 */
    private BigDecimal totalAmount;
    /** 实付金额。 */
    private BigDecimal payAmount;
    /** 运费金额。 */
    private BigDecimal freightAmount;
    /** 收货人姓名。 */
    private String receiverName;
    /** 收货人手机号。 */
    private String receiverPhone;
    /** 收货地址。 */
    private String receiverAddress;
    /** 订单备注。 */
    private String remark;
    /** 订单明细列表。 */
    private List<OrderItem> items;
    /** 创建时间。 */
    private LocalDateTime createTime;
    /** 支付时间。 */
    private LocalDateTime payTime;
    /** 发货时间。 */
    private LocalDateTime deliveryTime;
    /** 收货时间。 */
    private LocalDateTime receiveTime;
    /** 更新时间。 */
    private LocalDateTime updateTime;
}

package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 订单主表实体。
 * <p>
 * 表名从 `order` 改为 `orders`：`order` 是 SQL 标准保留字（PG/MySQL 都需要引号转义，
 * 语法互不兼容）。统一改成 `orders` 避免方言引号冲突。MySQL 和 PG 两侧都已 rename table。
 */
@Data
@TableName("orders")
public class Order {
    /** 订单 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 下单用户 ID。 */
    private Long userId;
    /** 订单编号。 */
    private String orderNo;
    /** 订单状态：0 待付款，1 待发货，2 待收货，3 已完成，4 已取消。 */
    private Integer status;
    /** 订单总金额。 */
    private BigDecimal totalAmount;
    /** 实付金额。 */
    private BigDecimal payAmount;
    /** 运费金额。 */
    private BigDecimal freightAmount;
    /** 收货地址 ID。 */
    private Long addressId;
    /** 收货人姓名。 */
    private String receiverName;
    /** 收货人手机号。 */
    private String receiverPhone;
    /** 收货详细地址。 */
    private String receiverAddress;
    /** 订单备注。 */
    private String remark;
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

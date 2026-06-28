package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.math.BigDecimal;

/**
 * 订单商品明细实体。
 */
@Data
@TableName("order_item")
public class OrderItem {
    /** 订单明细 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 订单 ID。 */
    private Long orderId;
    /** 商品 ID。 */
    private Long productId;
    /** 下单时的商品标题快照。 */
    private String productTitle;
    /** 下单时的商品图片快照。 */
    private String productImage;
    /** SKU ID。 */
    private Long skuId;
    /** 下单时的 SKU 属性快照。 */
    private String skuProperties;
    /** 商品单价。 */
    private BigDecimal price;
    /** 购买数量。 */
    private Integer quantity;
    /** 明细总金额。 */
    private BigDecimal totalAmount;
}

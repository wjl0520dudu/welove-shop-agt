package com.demo.weloveShopSystem.dto;

import lombok.Data;
import java.util.List;

/**
 * 创建订单请求参数。
 */
@Data
public class CreateOrderRequest {
    /** 收货地址 ID。 */
    private Long addressId;
    /** 订单商品明细列表。 */
    private List<OrderItemDto> items;
    /** 订单备注。 */
    private String remark;
    /** 收货人姓名。 */
    private String receiverName;
    /** 收货人手机号。 */
    private String receiverPhone;

    /**
     * 订单中的单个商品明细。
     */
    @Data
    public static class OrderItemDto {
        /** 商品 ID。 */
        private Long productId;
        /** 商品 SKU ID，表示具体规格。 */
        private Long skuId;
        /** 购买数量。 */
        private Integer quantity;
    }
}

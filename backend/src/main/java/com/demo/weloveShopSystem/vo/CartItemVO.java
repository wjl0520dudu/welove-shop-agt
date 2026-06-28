package com.demo.weloveShopSystem.vo;

import com.demo.weloveShopSystem.entity.Product;
import com.demo.weloveShopSystem.entity.ProductSku;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 购物车列表返回视图对象，包含购物车条目、商品信息和 SKU 信息。
 */
@Data
public class CartItemVO {
    /** 购物车条目 ID。 */
    private Long id;
    /** 用户 ID。 */
    private Long userId;
    /** 商品 ID。 */
    private Long productId;
    /** SKU ID。 */
    private Long skuId;
    /** 商品数量。 */
    private Integer quantity;
    /** 创建时间。 */
    private LocalDateTime createTime;
    /** 更新时间。 */
    private LocalDateTime updateTime;

    /** 商品信息。 */
    private Product product;

    /** SKU 信息。 */
    private ProductSku sku;

    /**
     * 计算当前购物车条目的总价，优先使用 SKU 价格，缺省时使用商品基础价格。
     */
    public BigDecimal getTotalPrice() {
        BigDecimal price = BigDecimal.ZERO;
        if (sku != null && sku.getPrice() != null) {
            price = sku.getPrice();
        } else if (product != null && product.getBasePrice() != null) {
            price = product.getBasePrice();
        }
        return price.multiply(BigDecimal.valueOf(quantity));
    }
}

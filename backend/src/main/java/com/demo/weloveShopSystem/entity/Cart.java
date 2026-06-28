package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 购物车条目实体。
 */
@Data
@TableName("user_cart")
public class Cart {
    /** 购物车条目 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 用户 ID。 */
    private Long userId;
    /** 商品 ID。 */
    private Long productId;
    /** SKU ID，表示商品具体规格。 */
    private Long skuId;
    /** 商品数量。 */
    private Integer quantity;
    /** 创建时间。 */
    private LocalDateTime createTime;
    /** 更新时间。 */
    private LocalDateTime updateTime;
}

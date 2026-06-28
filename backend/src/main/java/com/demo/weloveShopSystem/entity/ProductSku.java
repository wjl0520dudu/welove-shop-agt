package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;

/**
 * 商品 SKU 实体，表示商品的具体规格组合。
 */
@Data
@TableName(value = "product_sku", autoResultMap = true)
public class ProductSku {
    /** SKU ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 所属商品 ID。 */
    private Long productId;
    /** SKU 编码。 */
    private String skuCode;
    /** 规格属性，例如容量、颜色、尺码。 */
    @com.baomidou.mybatisplus.annotation.TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, String> properties;
    /** SKU 价格。 */
    private BigDecimal price;
    /** SKU 库存。 */
    private Integer stock;
    /** 是否默认规格。 */
    private Boolean isDefault;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

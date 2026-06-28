package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 商品实体。
 */
@Data
@TableName("product")
public class Product {
    /** 商品 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 商品编码。 */
    private String productCode;
    /** 所属分类 ID。 */
    private Long categoryId;
    /** 商品标题。 */
    private String title;
    /** 品牌名称。 */
    private String brand;
    /** 子分类。 */
    private String subCategory;
    /** 基础价格。 */
    private BigDecimal basePrice;
    /** 主图地址。 */
    private String imageUrl;
    /** 商品描述。 */
    private String description;
    /** 商品标签。 */
    private String tags;
    /** 评分。 */
    private BigDecimal rating;
    /** 评价数量。 */
    private Integer reviewCount;
    /** 销量。 */
    private Integer salesCount;
    /** 商品状态，通常 1 表示上架。 */
    private Integer status;
    /** 向量索引状态。 */
    private Integer embeddingStatus;
    /** 创建时间。 */
    private LocalDateTime createTime;
    /** 更新时间。 */
    private LocalDateTime updateTime;
}

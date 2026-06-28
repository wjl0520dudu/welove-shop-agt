package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 商品图片实体。
 */
@Data
@TableName("product_image")
public class ProductImage {
    /** 图片 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 商品 ID。 */
    private Long productId;
    /** 图片 URL。 */
    private String imageUrl;
    /** 图片类型，例如主图、详情图。 */
    private String imageType;
    /** 排序值。 */
    private Integer sortOrder;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

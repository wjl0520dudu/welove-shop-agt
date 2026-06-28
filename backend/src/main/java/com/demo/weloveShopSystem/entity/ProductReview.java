package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 商品评价实体。
 */
@Data
@TableName("product_review")
public class ProductReview {
    /** 评价 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 商品 ID。 */
    private Long productId;
    /** 评价用户 ID。 */
    private Long userId;
    /** 展示昵称。 */
    private String nickname;
    /** 评分。 */
    private Integer rating;
    /** 评价内容。 */
    private String content;
    /** 是否匿名评价。 */
    private Boolean isAnonymous;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

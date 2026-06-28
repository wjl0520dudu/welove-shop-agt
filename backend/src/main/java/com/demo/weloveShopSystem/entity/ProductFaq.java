package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 商品常见问答实体。
 */
@Data
@TableName("product_faq")
public class ProductFaq {
    /** FAQ ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 商品 ID。 */
    private Long productId;
    /** 常见问题。 */
    private String question;
    /** 问题答案。 */
    private String answer;
    /** 排序值。 */
    private Integer sortOrder;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

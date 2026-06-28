package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 用户商品收藏实体。
 */
@Data
@TableName("user_favorite")
public class UserFavorite {
    /** 收藏 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 用户 ID。 */
    private Long userId;
    /** 商品 ID。 */
    private Long productId;
    /** 收藏时间。 */
    private LocalDateTime createTime;

    /** 商品名称，非数据库字段。 */
    @TableField(exist = false)
    private String productName;
    /** 商品图片，非数据库字段。 */
    @TableField(exist = false)
    private String productImage;
    /** 商品价格，非数据库字段。 */
    @TableField(exist = false)
    private java.math.BigDecimal productPrice;
}

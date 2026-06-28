package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 用户商品浏览历史实体。
 */
@Data
@TableName("user_browse_history")
public class UserBrowseHistory {
    /** 浏览历史 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 用户 ID。 */
    private Long userId;
    /** 商品 ID。 */
    private Long productId;
    /** 浏览来源，例如推荐、搜索、详情页。 */
    private String source;
    /** 浏览停留时长，单位秒。 */
    private Integer durationSec;
    /** 创建时间。 */
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

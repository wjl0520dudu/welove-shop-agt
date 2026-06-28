package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 商品分类实体。
 */
@Data
@TableName("category")
public class Category {
    /** 分类 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 分类名称。 */
    private String name;
    /** 分类描述。 */
    private String description;
    /** 分类图标 URL。 */
    private String iconUrl;
    /** 排序值，越小越靠前。 */
    private Integer sortOrder;
    /** 是否启用。 */
    private Boolean isActive;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

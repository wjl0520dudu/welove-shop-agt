package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 用户收货地址实体。
 */
@Data
@TableName("address")
public class Address {
    /** 地址 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 所属用户 ID。 */
    private Long userId;
    /** 收货人姓名。 */
    private String receiverName;
    /** 收货人手机号。 */
    private String phone;
    /** 省份。 */
    private String province;
    /** 城市。 */
    private String city;
    /** 区县。 */
    private String district;
    /** 详细地址。 */
    private String detail;
    /** 是否默认地址，1 表示默认。 */
    private Integer isDefault;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

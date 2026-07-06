package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 普通用户实体。
 * <p>
 * 表名从 `user` 改为 `users`：`user` 是 PostgreSQL 里的保留字（等价于 CURRENT_USER 函数），
 * 直接用会被解析成当前会话用户名而非表。为兼容 PG，统一改表名为 `users`。
 * MySQL 端也已 rename table。
 */
@Data
@TableName(value = "users", autoResultMap = true)
public class User {
    /** 用户 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 用户名。 */
    private String username;
    /** 手机号。 */
    private String phone;

    /** 登录密码，接口序列化时忽略。 */
    @JsonIgnore
    private String password;

    /** 头像 URL。 */
    private String avatarUrl;
    /** 性别。 */
    private Integer gender;
    /** 年龄段。 */
    private String ageRange;
    /** 肤质。 */
    private String skinType;

    /** 偏好标签。 */
    @com.baomidou.mybatisplus.annotation.TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> preferenceTags;

    /** 用户状态。 */
    private Integer status;
    /** 创建时间。 */
    private LocalDateTime createTime;
    /** 更新时间。 */
    private LocalDateTime updateTime;
}

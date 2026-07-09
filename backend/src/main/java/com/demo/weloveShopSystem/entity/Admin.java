package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 管理员账号实体。
 * <p>
 * 与普通 users 表隔离:后台管理员没有手机号、性别、偏好标签等 C 端字段,
 * 单独一张 admin 表既方便权限收敛,也避免 users 表被业务字段污染。
 */
@Data
@TableName("admin")
public class Admin {
    /** 管理员 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 管理员用户名,登录用。 */
    private String username;

    /** 登录密码;推荐存 BCrypt 密文,接口序列化时忽略。 */
    @JsonIgnore
    private String password;

    /** 管理员角色,预留多级管理员场景(SUPER_ADMIN / OPERATOR 等),默认写 ADMIN 即可。 */
    private String role;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

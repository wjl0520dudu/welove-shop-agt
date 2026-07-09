package com.demo.weloveShopSystem.dto;

import lombok.Data;

import java.util.List;

/**
 * 更新用户资料请求参数。
 */
@Data
public class UpdateUserRequest {
    /** 用户 ID;实际业务中以后端从 JWT 解析出的用户 ID 为准。 */
    private Long userId;
    /** 用户名。 */
    private String username;
    /** 密码;用于资料更新时同步修改密码的场景。 */
    private String password;
    /** 用户头像 URL。 */
    private String avatarUrl;
    /** 性别枚举值,例如 0 未知、1 男、2 女,具体含义由业务约定。 */
    private Integer gender;
    /** 年龄段,例如 18-24、25-34。 */
    private String ageRange;
    /** 肤质,例如干皮、油皮、混合皮、敏感肌。 */
    private String skinType;
    /** 用户偏好标签,用于商品推荐和个性化回答。 */
    private List<String> preferenceTags;
}

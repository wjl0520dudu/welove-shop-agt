package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 聊天会话实体。
 */
@Data
@TableName("conversation")
public class Conversation {
    /** 会话 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 所属用户 ID。 */
    private Long userId;
    /** 会话标题。 */
    private String title;
    /** 会话场景，例如普通聊天或管理员助手。 */
    private String scene;
    /** 是否置顶。 */
    private Boolean isPinned;
    /** 创建时间。 */
    private LocalDateTime createTime;
    /** 更新时间。 */
    private LocalDateTime updateTime;

    /** 会话消息数量，非数据库字段。 */
    @TableField(exist = false)
    private Integer messageCount;
}

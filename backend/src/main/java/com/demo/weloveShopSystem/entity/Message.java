package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 会话消息实体。
 */
@Data
@TableName(value = "message", autoResultMap = true)
public class Message {
    /** 消息 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 所属会话 ID。 */
    private Long conversationId;
    /** 消息角色，例如 user 或 assistant。 */
    private String role;
    /** 消息文本内容。 */
    private String content;
    /** 消息类型，例如 text、product_card、cart_selection。 */
    private String messageType;
    /** 推荐商品卡片数据。 */
    @com.baomidou.mybatisplus.annotation.TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> productCards;
    /** 需要用户确认的操作卡片数据。 */
    @com.baomidou.mybatisplus.annotation.TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> confirmCard;
    /** 购物车选择卡片数据。 */
    @com.baomidou.mybatisplus.annotation.TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> cartSelection;
    /** 关联图片 URL。 */
    private String imageUrl;
    /** AI 回答引用来源。 */
    private String sources;
    /** AI 任务类型。 */
    private String taskType;
    /** 消息重要性评分。 */
    private Double importanceScore;
    /** 用户反馈类型，例如 like 或 dislike。 */
    private String feedbackType;
    /** 用户反馈时间。 */
    private LocalDateTime feedbackTime;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 对话上下文实体。
 * 用于管理对话短期记忆、摘要、用户偏好和长期记忆。
 */
@Data
@TableName("conversation_context")
public class ConversationContext {

    /** 上下文记录 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 会话 ID。 */
    private Long conversationId;

    /** 用户 ID。 */
    private Long userId;

    /** 对话摘要，作为长期记忆保存。 */
    private String summary;

    /** 对话向量表示，通常为 JSON 格式，用于相似对话检索。 */
    private String embedding;

    /** 本轮对话提取出的用户偏好，通常为 JSON 格式。 */
    private String userPreferences;

    /** 本轮对话中提到的商品 ID 列表，通常为 JSON 格式。 */
    private String mentionedProducts;

    /** 上下文窗口大小。 */
    private Integer windowSize;

    /** 对话重要性评分，用于决定是否长期保存。 */
    private Double importanceScore;

    /** 最后更新时间。 */
    private LocalDateTime updateTime;

    /** 创建时间。 */
    private LocalDateTime createTime;

    /**
     * 对话上下文中的单条消息。
     */
    @Data
    public static class ContextMessage {
        /** 消息角色，例如 user 或 assistant。 */
        private String role;
        /** 消息内容。 */
        private String content;
        /** 来源信息，通常为 JSON 格式。 */
        private String sources;
        /** 消息时间。 */
        private LocalDateTime timestamp;
        /** 消息重要性评分。 */
        private Double importance;
    }

    /**
     * 对话摘要结构。
     */
    @Data
    public static class ConversationSummary {
        /** 关键话题。 */
        private String keyTopics;
        /** 关键决策。 */
        private String keyDecisions;
        /** 用户偏好。 */
        private String userPreferences;
        /** 待办事项。 */
        private String actionItems;
        /** 最后更新时间。 */
        private LocalDateTime lastUpdated;
    }
}

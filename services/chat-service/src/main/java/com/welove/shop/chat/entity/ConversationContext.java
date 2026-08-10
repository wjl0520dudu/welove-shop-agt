package com.welove.shop.chat.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serial;
import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@TableName("conversation_context")
public class ConversationContext implements Serializable {
    @Serial private static final long serialVersionUID = 1L;
    @TableId(type = IdType.AUTO) private Long id;
    private Long conversationId;
    private Long userId;
    private String summary;
    /** Last visible message already represented by {@link #summary}. */
    private Long summaryCoveredMessageId;
    /** Last visible message that completed a configured summary batch. */
    private Long summaryCheckpointMessageId;
    private String embedding;
    private String userPreferences;
    private String mentionedProducts;
    private Integer windowSize;
    private Double importanceScore;
    private LocalDateTime updateTime;
    private LocalDateTime createTime;

    @Data
    public static class ContextMessage {
        private String role;
        private String content;
        private String sources;
        private LocalDateTime timestamp;
        private Double importance;
    }

    @Data
    public static class ConversationSummary {
        private String keyTopics;
        private String keyDecisions;
        private String userPreferences;
        private String actionItems;
        private LocalDateTime lastUpdated;
    }
}

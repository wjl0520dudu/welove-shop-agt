package com.welove.shop.chat.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;

import java.io.Serial;
import java.io.Serializable;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Data
@TableName(value = "message", autoResultMap = true)
public class Message implements Serializable {
    @Serial private static final long serialVersionUID = 1L;
    @TableId(type = IdType.AUTO) private Long id;
    private Long conversationId;
    /** Request-scoped turn identifier shared by the corresponding user and assistant messages. */
    private String turnId;
    /** New assistant message that superseded this historical response. */
    private Long supersededByMessageId;
    private String role;
    private String content;
    private String messageType;
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> productCards;
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> confirmCard;
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> cartSelection;
    private String imageUrl;
    private String sources;
    private String taskType;
    /** Persisted DAG plan / execution summary for conversation replay. */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> agentMeta;
    private Double importanceScore;
    private String feedbackType;
    private LocalDateTime feedbackTime;
    private String status;             // done|streaming|truncated|error
    private String stoppedReason;      // user_abort|server_error|null
    private LocalDateTime stoppedAt;
    private LocalDateTime createTime;
}

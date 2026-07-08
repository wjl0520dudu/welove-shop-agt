package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * AI 问答日志实体。
 */
@Data
@TableName("qa_log")
public class QaLog {
    /** 日志 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 用户 ID。 */
    private Long userId;
    /** 会话 ID。 */
    private Long conversationId;
    /** 用户问题。 */
    private String question;
    /** AI 回答。 */
    private String answer;
    /** 任务类型。 */
    private String taskType;
    /** 问答耗时，单位毫秒。 */
    private Long durationMs;
    /** 反馈类型，例如 like 或 dislike。 */
    private String feedbackType;
    /** 反馈时间。 */
    private LocalDateTime feedbackTime;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

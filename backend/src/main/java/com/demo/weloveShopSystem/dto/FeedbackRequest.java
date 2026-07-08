package com.demo.weloveShopSystem.dto;

import lombok.Data;

/**
 * 用户对 AI 消息的反馈请求。
 */
@Data
public class FeedbackRequest {
    /** 被反馈的消息 ID。 */
    private Long messageId;
    /** 反馈类型，例如 like 或 dislike。 */
    private String feedbackType;
}

package com.welove.shop.chat.dto;

import lombok.Data;

import java.io.Serial;
import java.io.Serializable;
import java.util.List;

@Data
public class StreamChatRequest implements Serializable {
    @Serial private static final long serialVersionUID = 1L;
    private Long userId;
    private Long conversationId;
    private String content;
    /** Optional OSS image URL. The AI service selects the retrieval paths from this field. */
    private String imageUrl;
    private String username;
    private boolean isAdmin;
    private String gender;
    private String skinType;
    private List<String> preferenceTags;
    /** Stable UUID for one user submit. Network retries must reuse it. */
    private String clientRequestId;
    private Long replacesAssistantMessageId;
    /** 是否为「重新生成」请求,后端据此跳过 dedup (避免 retry 触发相同的截断) */
    private boolean retry;
}

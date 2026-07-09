package com.demo.weloveShopSystem.dto;

import lombok.Data;

/**
 * 普通聊天请求参数。
 */
@Data
public class ChatRequest {
    /** 前端传入的用户 ID；实际业务中以后端从 JWT 解析出的用户 ID 为准。 */
    private Long userId;
    /** 当前消息所属的会话 ID。 */
    private Long conversationId;
    /** 用户发送的聊天内容。 */
    private String content;
}

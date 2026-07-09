package com.demo.weloveShopSystem.dto;

import lombok.Data;

import java.util.List;

/**
 * SSE 流式聊天请求参数。
 */
@Data
public class StreamChatRequest {
    /** 前端传入的用户 ID；实际业务中以后端从 JWT 解析出的用户 ID 为准。 */
    private Long userId;
    /** 当前消息所属的会话 ID。 */
    private Long conversationId;
    /** 用户发送的消息内容。 */
    private String content;
    /** 用户名，可传给 AI 用于个性化表达。 */
    private String username;
    /** 是否为管理员模式。 */
    private boolean isAdmin;
    /** 用户性别，用于推荐画像。 */
    private String gender;
    /** 用户肤质，例如干皮、油皮、混合皮、敏感肌。 */
    private String skinType;
    /** 用户偏好标签，例如保湿、平价、国货、敏感肌。 */
    private List<String> preferenceTags;
}

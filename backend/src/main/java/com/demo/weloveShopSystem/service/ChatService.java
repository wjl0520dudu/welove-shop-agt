package com.demo.weloveShopSystem.service;


import com.demo.weloveShopSystem.entity.Conversation;
import com.demo.weloveShopSystem.entity.Message;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

/**
 * 用户聊天服务接口。
 */
public interface ChatService {
    /** 创建新会话。 */
    Conversation createConversation(Long userId, String title);
    /** 查询用户历史会话。 */
    List<Conversation> getHistory(Long userId);
    /** 发送普通聊天消息并返回 AI 回复。 */
    Message sendMessage(Long userId, Long conversationId, String content, String jwtToken);
    /** 查询指定会话的消息列表。 */
    List<Message> getMessages(Long conversationId);
    /** 删除会话及其消息。 */
    void deleteConversation(Long conversationId);
    /** 更新会话标题或置顶状态。 */
    Conversation updateConversation(Long conversationId, String title, Boolean isPinned);
    /** 提交用户对 AI 消息的反馈。 */
    Message submitFeedback(Long messageId, String feedbackType);
    /** 保存客户端本地生成或补偿写入的消息。 */
    Message saveMessage(Long conversationId, String role, String content, String messageType);

    /**
     * SSE 流式发送消息，透传 Python AI 服务的事件流。
     *
     * @param userId         用户 ID
     * @param conversationId 会话 ID
     * @param content        消息内容
     * @param username       用户名，可为空
     * @param isAdmin        是否管理员模式
     * @param jwtToken       当前请求携带的 JWT token
     * @return SSE 发射器
     */
    SseEmitter sendStreamMessage(Long userId, Long conversationId, String content, String username, boolean isAdmin, String jwtToken);

    /**
     * SSE 流式发送消息，附带用户画像信息用于个性化推荐。
     *
     * @param userId         用户 ID
     * @param conversationId 会话 ID
     * @param content        消息内容
     * @param username       用户名，可为空
     * @param isAdmin        是否管理员模式
     * @param gender         用户性别
     * @param skinType       用户肤质
     * @param preferenceTags 用户偏好标签
     * @param jwtToken       当前请求携带的 JWT token
     * @return SSE 发射器
     */
    SseEmitter sendStreamMessage(Long userId, Long conversationId, String content,
                                  String username, boolean isAdmin,
                                  String gender, String skinType, List<String> preferenceTags,
                                  String jwtToken);
}

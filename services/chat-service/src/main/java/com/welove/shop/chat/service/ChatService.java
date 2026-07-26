package com.welove.shop.chat.service;

import com.welove.shop.chat.dto.FeedbackRequest;
import com.welove.shop.chat.entity.Conversation;
import com.welove.shop.chat.entity.Message;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.Map;

public interface ChatService {
    /** 新建会话。 */
    Conversation createConversation(Long userId, String title);
    /** 历史会话列表(置顶在前)。 */
    List<Conversation> getHistory(Long userId);
    /** 消息列表(带 Redis 缓存)。 */
    List<Message> getMessages(Long conversationId);
    /** 非流式发送消息。 */
    Message sendMessage(Long userId, Long conversationId, String content, String jwtToken);
    /** 流式发送消息(SSE) —— 返回 SseEmitter,Controller 层用。 */
    org.springframework.web.servlet.mvc.method.annotation.SseEmitter sendStreamMessage(
            Long userId, Long conversationId, String content, String imageUrl, String username,
            String jwtToken, String gender, String skinType, java.util.List<String> preferenceTags,
            boolean retry);
    /**
     * 多模态图文流式发送消息(SSE)。
     * <p>与 {@link #sendStreamMessage} 的区别:
     * <ul>
     *   <li>额外接收 {@code imageUrl}(先走 /chat/upload/image 拿到的 OSS URL)</li>
     *   <li>{@code content} 允许为空("纯图搜索"场景)</li>
     *   <li>与文本请求共用 ai-service /assistant/stream，是否带图由 imageUrl 决定</li>
     *   <li>user 消息落库时 message_type=multimodal_image 且写入 image_url</li>
     * </ul></p>
     */
    org.springframework.web.servlet.mvc.method.annotation.SseEmitter sendMultimodalStreamMessage(
            Long userId, Long conversationId, String content, String imageUrl,
            String username, String jwtToken, String gender, String skinType,
            java.util.List<String> preferenceTags, boolean retry);
    /**
     * 聊天图片上传:走 common-storage 的 StorageService,存到 OSS 后返回 {objectKey, url}。
     * <p>校验:MIME 必须是 image/*,大小 &le; 上限(默认 10MB,可通过配置调整)。</p>
     * <p>失败抛 {@link IllegalArgumentException},由全局异常处理器转 400。</p>
     */
    Map<String, Object> uploadChatImage(MultipartFile file) throws IOException;
    /** 删除会话(级联消息)。 */
    void deleteConversation(Long conversationId);
    /** 更新会话(标题/置顶)。 */
    void updateConversation(Long conversationId, String title, Boolean isPinned);
    /** 消息反馈。 */
    void submitFeedback(FeedbackRequest request);
    /**
     * 前端 abort 时主动把半成品发到后端落库(status=truncated)。
     * 与 doOnCancel 兜底共享同一去重逻辑,clientTs 用于冲突判优。
     * 返回新插入(或已存在去重命中)的 message id。
     */
    Long persistTruncatedFromClient(Long userId, Long conversationId, String content,
                                    List<Map<String, Object>> productCards,
                                    Map<String, Object> confirmCard,
                                    Map<String, Object> cartSelection,
                                    String taskType, Long clientTs);
}

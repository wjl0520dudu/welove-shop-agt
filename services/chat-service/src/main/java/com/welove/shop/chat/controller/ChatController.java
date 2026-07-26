package com.welove.shop.chat.controller;

import com.welove.shop.chat.dto.ChatRequest;
import com.welove.shop.chat.dto.FeedbackRequest;
import com.welove.shop.chat.dto.MultimodalStreamChatRequest;
import com.welove.shop.chat.dto.StopMessageRequest;
import com.welove.shop.chat.dto.StreamChatRequest;
import com.welove.shop.chat.entity.Conversation;
import com.welove.shop.chat.entity.Message;
import com.welove.shop.chat.service.ChatService;
import com.welove.shop.common.core.result.Result;
import com.welove.shop.common.security.context.UserContext;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/chat")
@RequiredArgsConstructor
public class ChatController {
    private final ChatService chatService;

    @PostMapping("/conversations") public Result<Conversation> createConversation(@RequestParam(required = false, defaultValue = "New Chat") String title) {
        return Result.ok(chatService.createConversation(UserContext.requireUserId(), title));
    }
    @GetMapping("/conversations") public Result<List<Conversation>> getHistory() {
        return Result.ok(chatService.getHistory(UserContext.requireUserId()));
    }
    @PostMapping("/messages") public Result<Message> sendMessage(@RequestBody ChatRequest req) {
        Long uid = UserContext.requireUserId();
        Message m = chatService.sendMessage(uid, req.getConversationId(), req.getContent(), null);
        return m != null ? Result.ok(m) : Result.ok();
    }
    @PostMapping(value = "/stream/messages", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamMessages(@RequestBody StreamChatRequest req, HttpServletRequest httpReq) {
        String jwtToken = extractJwt(httpReq);
        return chatService.sendStreamMessage(
                UserContext.requireUserId(),
                req.getConversationId(),
                req.getContent(),
                req.getImageUrl(),
                req.getUsername() != null ? req.getUsername() : "user",
                jwtToken,
                req.getGender(),
                req.getSkinType(),
                req.getPreferenceTags(),
                req.isRetry()
        );
    }

    /**
     * 多模态图文流式聊天端点。请求前先调 {@link #uploadImage} 拿到 OSS URL。
     * <p>与 {@link #streamMessages} 的区别:请求体必须带 imageUrl,content 可为空
     * (纯图搜索)。该 URL 仅保留兼容，内部与主入口统一转发到 ai-service /assistant/stream。</p>
     * <p>图片校验策略:chat-service 只在 {@link #uploadImage} 上传时做 MIME/大小校验;
     * 转发时不再 HEAD 预检 —— ai-service 侧 HEAD + DashScope 兜底会拦下坏图,
     * 通过 SSE error 事件透传给前端。</p>
     */
    @PostMapping(value = "/multimodal/stream/messages", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamMultimodalMessages(@RequestBody MultimodalStreamChatRequest req,
                                                HttpServletRequest httpReq) {
        String jwtToken = extractJwt(httpReq);
        return chatService.sendStreamMessage(
                UserContext.requireUserId(),
                req.getConversationId(),
                req.getContent(),
                req.getImageUrl(),
                req.getUsername() != null ? req.getUsername() : "user",
                jwtToken,
                req.getGender(),
                req.getSkinType(),
                req.getPreferenceTags(),
                req.isRetry()
        );
    }

    /**
     * 聊天图片上传:MultipartFile → common-storage → OSS,返回 {objectKey, url}。
     * <p>与 KnowledgeController 上传的区别:key-prefix 已在配置为 chat/,所以聊天
     * 图片存在 chat/yyyy-MM-dd/*.jpg 下,和知识库文档物理分开。</p>
     * <p>MIME 白名单和大小上限由 chat-service.upload.image.* 配置控制;超限抛
     * IllegalArgumentException,由全局异常处理器转 400。</p>
     */
    @PostMapping(value = "/upload/image", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<Map<String, Object>> uploadImage(@RequestParam MultipartFile file) throws IOException {
        // requireUserId 兜底一次:即使 gateway 忘了鉴权也不给匿名用户传图
        UserContext.requireUserId();
        return Result.ok(chatService.uploadChatImage(file));
    }
    @GetMapping("/messages") public Result<List<Message>> getMessages(@RequestParam Long conversationId) {
        return Result.ok(chatService.getMessages(conversationId));
    }
    @DeleteMapping("/conversations/{id}") public Result<Void> deleteConversation(@PathVariable Long id) {
        chatService.deleteConversation(id); return Result.ok();
    }
    @PutMapping("/conversations/{id}") public Result<Void> updateConversation(@PathVariable Long id, @RequestParam(required = false) String title, @RequestParam(required = false) Boolean isPinned) {
        chatService.updateConversation(id, title, isPinned); return Result.ok();
    }
    @PostMapping("/messages/feedback") public Result<Void> submitFeedback(@RequestBody FeedbackRequest req) {
        chatService.submitFeedback(req); return Result.ok();
    }
    /**
     * 客户端中止流时主动把半成品发到后端落库,保证刷新后仍能看到截断回复。
     * 双保险:即便此请求因网络断开未送达,后端 Flux.doOnCancel 也会兜底写一条。
     */
    @PostMapping("/messages/stop") public Result<Long> stopMessage(@RequestBody StopMessageRequest req) {
        Long messageId = chatService.persistTruncatedFromClient(
                UserContext.requireUserId(),
                req.getConversationId(),
                req.getContent(),
                req.getProductCards(),
                req.getConfirmCard(),
                req.getCartSelection(),
                req.getTaskType(),
                req.getClientTs()
        );
        return Result.ok(messageId);
    }

    /** 从请求头提取 JWT token (去 Bearer 前缀)。 */
    private String extractJwt(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")) {
            return header.substring(7);
        }
        return null;
    }
}

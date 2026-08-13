package com.welove.shop.chat.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.welove.shop.chat.dto.FeedbackRequest;
import com.welove.shop.chat.entity.Conversation;
import com.welove.shop.chat.entity.Message;
import com.welove.shop.chat.entity.QaLog;
import com.welove.shop.chat.mapper.ConversationMapper;
import com.welove.shop.chat.mapper.MessageMapper;
import com.welove.shop.chat.mapper.QaLogMapper;
import com.welove.shop.chat.service.AiService;
import com.welove.shop.chat.service.ConversationContextService;
import com.welove.shop.chat.service.ChatService;
import com.welove.shop.common.core.exception.BizException;
import com.welove.shop.common.storage.service.StorageService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.publisher.Flux;

import java.io.IOException;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;

@Slf4j
@Service
@RequiredArgsConstructor
public class ChatServiceImpl implements ChatService {
    private static final String DEDUP_PREFIX = "chat:dedup:";
    private static final String STATUS_DONE = "done";
    private static final String STATUS_TRUNCATED = "truncated";
    private static final String STOP_USER_ABORT = "user_abort";
    private static final String STOP_SERVER = "server_error";
    /** message.message_type: 纯文本消息。 */
    private static final String MSG_TYPE_TEXT = "text";
    /** message.message_type: 用户上传图片的多模态消息(assistant 消息不用这个 type)。 */
    private static final String MSG_TYPE_MULTIMODAL_IMAGE = "multimodal_image";
    /** 截断去重窗口(秒):同 conversation + 同 contentPrefix 在此窗口内只写一条。 */
    private static final int TRUNC_DEDUP_SECONDS = 60;
    private final ConversationMapper convMapper;
    private final MessageMapper msgMapper;
    private final QaLogMapper qaLogMapper;
    private final AiService aiService;
    private final ConversationContextService ctxService;
    private final RollingConversationSummaryService rollingSummaryService;
    private final ConversationTurnGuard conversationTurnGuard;
    private final StringRedisTemplate redisTemplate;
    private final WebClient webClient;
    private final ObjectMapper objectMapper;
    private final StorageService storageService;
    @Value("${chat-service.context.rolling-summary.enabled:true}") private boolean rollingSummaryEnabled;
    @Value("${chat-service.context.dedup-window-seconds:30}") private long dedupWindow;
    @Value("${chat-service.sse.timeout:300000}") private long sseTimeout;
    @Value("${chat-service.upload.image.max-bytes:10485760}") private long imageMaxBytes;
    @Value("${chat-service.upload.image.allowed-mime:image/jpeg,image/png,image/webp,image/gif}")
    private String imageAllowedMime;

    // ---------- CRUD ----------
    @Override public Conversation createConversation(Long userId, String title) {
        Conversation c = new Conversation();
        c.setUserId(userId); c.setTitle(title != null ? title : "New Chat " + LocalDateTime.now());
        c.setScene("normal"); c.setIsPinned(0);
        c.setCreateTime(LocalDateTime.now()); c.setUpdateTime(LocalDateTime.now());
        convMapper.insert(c); return c;
    }
    @Override public List<Conversation> getHistory(Long userId) {
        return convMapper.selectList(new LambdaQueryWrapper<Conversation>()
                .eq(Conversation::getUserId, userId)
                .orderByDesc(Conversation::getIsPinned).orderByDesc(Conversation::getCreateTime));
    }
    @Override public List<Message> getMessages(Long conversationId) {
        // The page history is the full persisted transcript, never the small
        // model-context window.  Context compression must not change what a
        // user can scroll back to in H5.
        return msgMapper.selectList(new LambdaQueryWrapper<Message>()
                .eq(Message::getConversationId, conversationId)
                .and(wrapper -> wrapper.ne(Message::getRole, "assistant")
                        .or()
                        .isNull(Message::getSupersededByMessageId))
                .orderByAsc(Message::getCreateTime)
                .orderByAsc(Message::getId));
    }
    @Override @Transactional public void deleteConversation(Long conversationId) {
        msgMapper.delete(new LambdaQueryWrapper<Message>().eq(Message::getConversationId, conversationId));
        convMapper.deleteById(conversationId);
    }
    @Override public void updateConversation(Long conversationId, String title, Boolean isPinned) {
        Conversation c = convMapper.selectById(conversationId);
        if (c != null) {
            if (title != null) c.setTitle(title);
            if (isPinned != null) c.setIsPinned(isPinned ? 1 : 0);
            c.setUpdateTime(LocalDateTime.now());
            convMapper.updateById(c);
        }
    }

    // ---------- sync ----------
    @Override @Transactional public Message sendMessage(Long userId, Long conversationId, String content, String jwtToken) {
        if (isDuplicate(conversationId, content)) return null;
        Message userMsg = saveUserMessage(conversationId, content);
        ctxService.updateConversationContext(conversationId, userId, userMsg);
        if (isFirstMessage(conversationId)) aiService.generateTitle(conversationId, content);
        long start = System.currentTimeMillis();
        Map<String, Object> aiResp = aiService.ask(content, List.of(), userId, null);
        long duration = System.currentTimeMillis() - start;
        Message aiMsg = new Message();
        aiMsg.setConversationId(conversationId); aiMsg.setRole("assistant");
        aiMsg.setContent(String.valueOf(aiResp.getOrDefault("answer", "")));
        aiMsg.setMessageType("text"); aiMsg.setTaskType(String.valueOf(aiResp.getOrDefault("task_type", "")));
        aiMsg.setCreateTime(LocalDateTime.now());
        msgMapper.insert(aiMsg);
        ctxService.invalidateConversationContext(conversationId);
        rollingSummaryService.scheduleUpdate(conversationId);
        saveQaLog(userId, conversationId, content, aiMsg.getContent(), aiMsg.getTaskType(), duration);
        return aiMsg;
    }

    // ---------- SSE stream ----------
    @Override public SseEmitter sendStreamMessage(Long userId, Long conversationId, String content,
                                                   String imageUrl, String username, String jwtToken,
                                                   String gender, String skinType, java.util.List<String> preferenceTags,
                                                   boolean retry, String clientRequestId,
                                                   Long replacesAssistantMessageId) {
        String turnId = normalizeTurnId(clientRequestId);
        if (!conversationTurnGuard.tryAcquire(conversationId, turnId)) {
            return rejectedTurnEmitter(conversationId, turnId);
        }
        if (imageUrl != null && !imageUrl.isBlank()) {
            return startMultimodalStreamMessage(
                    userId, conversationId, content, imageUrl, username, jwtToken,
                    gender, skinType, preferenceTags, retry, turnId, replacesAssistantMessageId
            );
        }
        return startTextStreamMessage(
                userId, conversationId, content, username, jwtToken,
                gender, skinType, preferenceTags, retry, turnId, replacesAssistantMessageId
        );
    }

    private SseEmitter startTextStreamMessage(Long userId, Long conversationId, String content,
                                               String username, String jwtToken, String gender, String skinType,
                                               java.util.List<String> preferenceTags, boolean retry, String turnId,
                                               Long replacesAssistantMessageId) {
        SseEmitter emitter = new SseEmitter(sseTimeout);
        final long streamStartMs = System.currentTimeMillis();
        // 用 AtomicBoolean 标记是否已正常完成,防止多个回调同时触发写库双写。
        java.util.concurrent.atomic.AtomicBoolean finalized = new java.util.concurrent.atomic.AtomicBoolean(false);
        // 把流式累积容器提升到闭包外,使 SseEmitter.onError/onCompletion/onTimeout 回调也能访问。
        StringBuilder answerBuilder = new StringBuilder();
        String[] taskType = {""};
        java.util.List<Map<String, Object>>[] productCards = new java.util.List[]{new java.util.ArrayList<>()};
        Map<String, Object>[] confirmCard = new Map[]{null};
        Map<String, Object>[] cartSelection = new Map[]{null};
        String[] sources = {""};
        Map<String, Object>[] agentMeta = new Map[]{new java.util.LinkedHashMap<>()};
        java.util.concurrent.atomic.AtomicReference<Long> assistantMessageId = new java.util.concurrent.atomic.AtomicReference<>();

        // ============= SseEmitter 生命周期回调 =============
        // onCompletion: 流正常关闭时调用(包括 emitter.complete() 和客户端正常断开)
        // onTimeout:     SSE 超时(sseTimeout)时调用
        // onError:       客户端断开时 Tomcat 抛 IOException 触发,这是 Spring 推荐的「客户端断开」信号。
        // doOnNext 中 try-catch emitter.send() 抛 IOException + 改走 doOnCancel 的思路不可靠(Reactor 内部信号竞态),
        // 这里直接用 SseEmitter 的回调,更稳定。
        emitter.onCompletion(() -> {
            // 正常关闭路径 (emitter.complete()) 不需要再落库,doOnComplete 已经处理
            log.debug("SseEmitter onCompletion conv={}", conversationId);
        });
        emitter.onTimeout(() -> {
            // SSE 超时也当作「客户端断开」处理(可能是网络差被服务器端提前关了)
            if (finalized.compareAndSet(false, true)) {
                log.info("SseEmitter onTimeout, persist truncated conv={}", conversationId);
                persistTruncatedInternal(conversationId, assistantMessageId.get(), answerBuilder.toString(),
                        productCards[0], confirmCard[0], cartSelection[0],
                        taskType[0], STOP_USER_ABORT);
            }
            emitter.complete();
        });
        emitter.onError((ex) -> {
            // 客户端断开 → 这是 Spring 官方推荐的「客户端断开」检测点
            if (finalized.compareAndSet(false, true)) {
                String exMsg = ex == null ? "" : ex.getMessage();
                log.info("SseEmitter onError (client likely disconnected): {}, persist truncated conv={}",
                        exMsg == null ? "(null)" : exMsg, conversationId);
                persistTruncatedInternal(conversationId, assistantMessageId.get(), answerBuilder.toString(),
                        productCards[0], confirmCard[0], cartSelection[0],
                        taskType[0], STOP_USER_ABORT);
            }
            // 不要再调用 emitter.complete()/send(),流已断,会再次抛异常
        });

        CompletableFuture.runAsync(() -> {
            try {
                Message existingAssistant = findAssistantByTurnId(conversationId, turnId);
                if (existingAssistant != null) {
                    replayExistingTurn(emitter, existingAssistant);
                    conversationTurnGuard.release(conversationId, turnId);
                    return;
                }
                // retry=true 时不再写用户消息；每次重新生成使用新的 turnId，避免
                // 与初始提交的幂等键混淆。
                if (!retry) {
                    Message userMsg = saveUserMessage(conversationId, content, null, turnId);
                    ctxService.updateConversationContext(conversationId, userId, userMsg);
                }
                if (!retry && isFirstMessage(conversationId)) aiService.generateTitle(conversationId, content);
                validateRegenerationTarget(conversationId, retry, replacesAssistantMessageId);
                Message streamingAssistant = createStreamingAssistant(conversationId, turnId);
                assistantMessageId.set(streamingAssistant.getId());
                applyRegenerationReplacement(conversationId, retry, replacesAssistantMessageId,
                        streamingAssistant.getId());

                // 拼 AI 请求体 —— 对齐 ai-service /api/assistant/stream 的 ChatRequest schema
                Map<String, Object> aiBody = new java.util.HashMap<>();
                aiBody.put("question", content);
                aiBody.put("conversation_id", conversationId.toString());
                aiBody.put("user_id", userId.toString());
                aiBody.put("conversation_history", buildConversationHistory(conversationId));
                aiBody.put("conversation_summary", buildConversationSummary(conversationId));
                aiBody.put("username", username);
                aiBody.put("is_admin", false);
                if (jwtToken != null) aiBody.put("jwt_token", jwtToken);
                if (gender != null) aiBody.put("gender", gender);
                if (skinType != null) aiBody.put("skin_type", skinType);
                if (preferenceTags != null) aiBody.put("preference_tags", preferenceTags);

                // WebClient 对 text/event-stream 会自动解码 SSE，用 ServerSentEvent<String>
                // 直接拿到事件名 event() 与已解码的 data 载荷，避免手工按物理行拆帧(会丢事件名)。
                org.springframework.core.ParameterizedTypeReference<org.springframework.http.codec.ServerSentEvent<String>> sseType =
                        new org.springframework.core.ParameterizedTypeReference<>() {};
                Flux<org.springframework.http.codec.ServerSentEvent<String>> flux = webClient.post()
                        .uri("/assistant/stream")
                        .accept(org.springframework.http.MediaType.TEXT_EVENT_STREAM)
                        .bodyValue(aiBody)
                        .retrieve().bodyToFlux(sseType);

                flux.doOnNext(sse -> {
                    // emitter.send() 抛 IOException 时(客户端断开),让其自然抛到 Reactor,
                    // 配合 SseEmitter.onError 回调落库。此处只需吞掉 JSON 解析异常,不让真正
                    // 的客户端断开被掩盖成 parse failed。
                    String eventType = sse.event() != null ? sse.event() : "message";
                    String data = sse.data();
                    if (data == null || data.isEmpty()) return;

                    try {
                        // 透传给前端(保留正确的事件名 + 原始 data JSON)。
                        // 上游 done 不透传:chat-service 在 doOnComplete 统一补发带 messageId 的 done,避免前端收到两个 done。
                        if (!"done".equals(eventType)) {
                            emitter.send(SseEmitter.event().name(eventType).data(data));
                        }
                    } catch (IOException ioe) {
                        // 客户端断开:不再吞,让 Reactor 进入 doOnError 兜底
                        throw new RuntimeException(ioe);
                    }

                    // 解析 data JSON 用于持久化收集 (这里独立 try,不影响 send)
                    Map<String, Object> event;
                    try {
                        event = objectMapper.readValue(data, Map.class);
                    } catch (IOException je) {
                        log.warn("SSE data JSON parse failed: {}", je.getMessage());
                        return;
                    }
                    switch (eventType == null ? "" : eventType) {
                        case "orchestrator_plan":
                        case "orchestrator_subtask":
                            captureOrchestratorMeta(eventType, event, agentMeta[0]);
                            break;
                        case "subtask_result":
                            captureSubtaskResult(event, answerBuilder, productCards[0]);
                            break;
                        case "token":
                            answerBuilder.append(event.getOrDefault("content", ""));
                            break;
                        case "route":
                            if (event.containsKey("task_type")) taskType[0] = String.valueOf(event.get("task_type"));
                            break;
                        case "final":
                            captureFinalAgentMeta(event, agentMeta[0]);
                            // ai-service 的 final data 即完整 AIResponse，字段在顶层(非嵌套 response)
                            Object finalAnswer = event.get("answer");
                            if (finalAnswer != null && !String.valueOf(finalAnswer).isBlank()) {
                                // final.answer is authoritative. Token frames are only for
                                // progressive rendering and may include intermediate text.
                                answerBuilder.setLength(0);
                                answerBuilder.append(finalAnswer);
                            }
                            if (event.containsKey("task_type")) taskType[0] = String.valueOf(event.get("task_type"));
                            if (event.get("product_cards") instanceof java.util.List<?> pc) {
                                mergeProductCards(productCards[0], pc);
                            }
                            if (event.get("confirm_card") instanceof Map<?, ?> cc) {
                                confirmCard[0] = (Map<String, Object>) cc;
                            }
                            if (event.get("cart_selection") instanceof Map<?, ?> cs) {
                                cartSelection[0] = (Map<String, Object>) cs;
                            }
                            if (event.containsKey("sources")) {
                                try {
                                    sources[0] = objectMapper.writeValueAsString(event.get("sources"));
                                } catch (IOException ignored) { }
                            }
                            break;
                        case "error":
                            log.warn("AI stream error: {}", event.getOrDefault("message", ""));
                            break;
                    }
                }).doOnComplete(() -> {
                    if (!finalized.compareAndSet(false, true)) return;
                    try {
                        String answer = answerBuilder.toString();
                        Message aiMsg = completeStreamingAssistant(
                                assistantMessageId.get(), answer, taskType[0], productCards[0],
                                confirmCard[0], cartSelection[0], sources[0], agentMeta[0]
                        );
                        ctxService.invalidateConversationContext(conversationId);
                        rollingSummaryService.scheduleUpdate(conversationId);
                        long streamDuration = System.currentTimeMillis() - streamStartMs;
                        saveQaLog(userId, conversationId, content, answer, taskType[0].isEmpty() ? "shopping" : taskType[0], streamDuration);
                        // 发送 done 事件并关闭 (set finalized 已在上面 compareAndSet 完成)
                        emitter.send(SseEmitter.event().name("done").data(Map.of("messageId", aiMsg.getId())));
                        emitter.complete();
                    } catch (Exception e) {
                        log.error("SSE onComplete save failed", e);
                        // finalize 已 true,onError 不会再触发;但要发 error 给前端(如果连接还在)
                        try {
                            emitter.send(SseEmitter.event().name("error").data(Map.of("content", e.getMessage())));
                        } catch (IOException ex) { }
                        emitter.complete();
                    }
                }).doOnError(e -> {
                    // Reactor 链上报错:不是客户端断开(已由 emitter.onError 兜底),
                    // 而是 ai-service 自身出错 / 网络异常等真正的服务端问题。
                    // 注意:即使客户端断开,WebClient 的上游 reader.read() 在 Reactor 内部也会走 doOnError,
                    // 所以这里需要再次兜底,避免与 emitter.onError 双写(finalized 已经保证只写一次)。
                    if (!finalized.compareAndSet(false, true)) {
                        log.debug("Reactor doOnError but already finalized (handled by emitter.onError) conv={}", conversationId);
                        return;
                    }
                    log.error("SSE stream error (ai-service upstream)", e);
                    String answer = answerBuilder.toString();
                    Long errId = persistTruncatedInternal(conversationId, assistantMessageId.get(), answer,
                            productCards[0], confirmCard[0], cartSelection[0],
                            taskType[0], STOP_SERVER);
                    try {
                        Map<String, Object> payload = new java.util.HashMap<>();
                        payload.put("content", String.valueOf(e.getMessage()));
                        if (errId != null) payload.put("messageId", errId);
                        emitter.send(SseEmitter.event().name("error").data(payload));
                    } catch (IOException ex) { }
                    emitter.complete();
                }).doFinally(signal -> conversationTurnGuard.release(conversationId, turnId)).subscribe();
            } catch (Exception e) {
                log.error("SSE setup error", e);
                if (finalized.compareAndSet(false, true)) {
                    persistTruncatedInternal(conversationId, assistantMessageId.get(), "", null, null, null, "", STOP_SERVER);
                }
                try {
                    emitter.send(SseEmitter.event().name("error").data(Map.of("content", e.getMessage())));
                    emitter.complete();
                } catch (IOException ex) { emitter.completeWithError(ex); }
                conversationTurnGuard.release(conversationId, turnId);
            }
        });
        return emitter;
    }

    // ---------- SSE multimodal stream (图 + 文) ----------
    /**
     * 多模态图文流式发送消息。与 {@link #sendStreamMessage} 的关键差异在下方注释中
     * 用 "MM-DIFF" 标记,便于对照:
     * <ul>
     *   <li>MM-DIFF-1:aiBody 多带一个 image_url</li>
     *   <li>MM-DIFF-2:WebClient 与文本请求共用 /assistant/stream，携带 image_url</li>
     *   <li>MM-DIFF-3:saveUserMessage 传 imageUrl,落 message_type=multimodal_image</li>
     *   <li>MM-DIFF-4:content 允许为空(纯图搜索);dedup 用带 [MM] 前缀区分</li>
     * </ul>
     * 其余(生命周期回调、doOnComplete 落 assistant、doOnCancel 截断、生成标题)
     * 与纯文本流一致 —— 直接照抄以保证行为等价,未来若发现更多多模态形式再重构成
     * 私有 core 方法。
     */
    @Override public SseEmitter sendMultimodalStreamMessage(Long userId, Long conversationId, String content,
                                                             String imageUrl, String username, String jwtToken,
                                                             String gender, String skinType, java.util.List<String> preferenceTags,
                                                             boolean retry, String clientRequestId,
                                                             Long replacesAssistantMessageId) {
        if (imageUrl == null || imageUrl.trim().isEmpty()) {
            throw new IllegalArgumentException("imageUrl 不能为空(多模态流式请求)");
        }
        String turnId = normalizeTurnId(clientRequestId);
        if (!conversationTurnGuard.tryAcquire(conversationId, turnId)) {
            return rejectedTurnEmitter(conversationId, turnId);
        }
        return startMultimodalStreamMessage(
                userId, conversationId, content, imageUrl, username, jwtToken,
                gender, skinType, preferenceTags, retry, turnId, replacesAssistantMessageId
        );
    }

    private SseEmitter startMultimodalStreamMessage(Long userId, Long conversationId, String content,
                                                      String imageUrl, String username, String jwtToken,
                                                      String gender, String skinType, java.util.List<String> preferenceTags,
                                                      boolean retry, String turnId,
                                                      Long replacesAssistantMessageId) {
        // MM-DIFF-4:content 可空,但 imageUrl 必须有 —— 控制器已经做了非空校验,这里防御性再判一次
        if (imageUrl == null || imageUrl.trim().isEmpty()) {
            throw new IllegalArgumentException("imageUrl 不能为空(多模态流式请求)");
        }
        String safeContent = content != null ? content : "";

        SseEmitter emitter = new SseEmitter(sseTimeout);
        final long streamStartMs = System.currentTimeMillis();
        java.util.concurrent.atomic.AtomicBoolean finalized = new java.util.concurrent.atomic.AtomicBoolean(false);
        StringBuilder answerBuilder = new StringBuilder();
        String[] taskType = {""};
        java.util.List<Map<String, Object>>[] productCards = new java.util.List[]{new java.util.ArrayList<>()};
        Map<String, Object>[] confirmCard = new Map[]{null};
        Map<String, Object>[] cartSelection = new Map[]{null};
        String[] sources = {""};
        Map<String, Object>[] agentMeta = new Map[]{new java.util.LinkedHashMap<>()};
        java.util.concurrent.atomic.AtomicReference<Long> assistantMessageId = new java.util.concurrent.atomic.AtomicReference<>();

        emitter.onCompletion(() -> log.debug("SseEmitter[MM] onCompletion conv={}", conversationId));
        emitter.onTimeout(() -> {
            if (finalized.compareAndSet(false, true)) {
                log.info("SseEmitter[MM] onTimeout, persist truncated conv={}", conversationId);
                persistTruncatedInternal(conversationId, assistantMessageId.get(), answerBuilder.toString(),
                        productCards[0], confirmCard[0], cartSelection[0],
                        taskType[0], STOP_USER_ABORT);
            }
            emitter.complete();
        });
        emitter.onError((ex) -> {
            if (finalized.compareAndSet(false, true)) {
                String exMsg = ex == null ? "" : ex.getMessage();
                log.info("SseEmitter[MM] onError (client likely disconnected): {}, persist truncated conv={}",
                        exMsg == null ? "(null)" : exMsg, conversationId);
                persistTruncatedInternal(conversationId, assistantMessageId.get(), answerBuilder.toString(),
                        productCards[0], confirmCard[0], cartSelection[0],
                        taskType[0], STOP_USER_ABORT);
            }
        });

        CompletableFuture.runAsync(() -> {
            try {
                Message existingAssistant = findAssistantByTurnId(conversationId, turnId);
                if (existingAssistant != null) {
                    replayExistingTurn(emitter, existingAssistant);
                    conversationTurnGuard.release(conversationId, turnId);
                    return;
                }
                // MM-DIFF-3:落 user 消息时带 imageUrl
                if (!retry) {
                    Message userMsg = saveUserMessage(conversationId, safeContent, imageUrl, turnId);
                    ctxService.updateConversationContext(conversationId, userId, userMsg);
                }
                if (!retry && isFirstMessage(conversationId)) {
                    // 纯图搜索没有 content,用占位符生成标题;LLM 侧看到 [图片] 会尝试生成"图片搜索"类标题
                    aiService.generateTitle(conversationId, safeContent.isEmpty() ? "[图片]" : safeContent);
                }
                validateRegenerationTarget(conversationId, retry, replacesAssistantMessageId);
                Message streamingAssistant = createStreamingAssistant(conversationId, turnId);
                assistantMessageId.set(streamingAssistant.getId());
                applyRegenerationReplacement(conversationId, retry, replacesAssistantMessageId,
                        streamingAssistant.getId());

                Map<String, Object> aiBody = new java.util.HashMap<>();
                aiBody.put("question", safeContent);
                aiBody.put("image_url", imageUrl);  // MM-DIFF-1
                aiBody.put("conversation_id", conversationId.toString());
                aiBody.put("user_id", userId.toString());
                aiBody.put("conversation_history", buildConversationHistory(conversationId));
                aiBody.put("conversation_summary", buildConversationSummary(conversationId));
                aiBody.put("username", username);
                aiBody.put("is_admin", false);
                if (jwtToken != null) aiBody.put("jwt_token", jwtToken);
                if (gender != null) aiBody.put("gender", gender);
                if (skinType != null) aiBody.put("skin_type", skinType);
                if (preferenceTags != null) aiBody.put("preference_tags", preferenceTags);

                org.springframework.core.ParameterizedTypeReference<org.springframework.http.codec.ServerSentEvent<String>> sseType =
                        new org.springframework.core.ParameterizedTypeReference<>() {};
                Flux<org.springframework.http.codec.ServerSentEvent<String>> flux = webClient.post()
                        .uri("/assistant/stream")
                        .accept(org.springframework.http.MediaType.TEXT_EVENT_STREAM)
                        .bodyValue(aiBody)
                        .retrieve().bodyToFlux(sseType);

                flux.doOnNext(sse -> {
                    String eventType = sse.event() != null ? sse.event() : "message";
                    String data = sse.data();
                    if (data == null || data.isEmpty()) return;

                    try {
                        if (!"done".equals(eventType)) {
                            emitter.send(SseEmitter.event().name(eventType).data(data));
                        }
                    } catch (IOException ioe) {
                        throw new RuntimeException(ioe);
                    }

                    Map<String, Object> event;
                    try {
                        event = objectMapper.readValue(data, Map.class);
                    } catch (IOException je) {
                        log.warn("SSE[MM] data JSON parse failed: {}", je.getMessage());
                        return;
                    }
                    switch (eventType) {
                        case "orchestrator_plan":
                        case "orchestrator_subtask":
                            captureOrchestratorMeta(eventType, event, agentMeta[0]);
                            break;
                        case "subtask_result":
                            captureSubtaskResult(event, answerBuilder, productCards[0]);
                            break;
                        case "token":
                            answerBuilder.append(event.getOrDefault("content", ""));
                            break;
                        case "route":
                            if (event.containsKey("task_type")) taskType[0] = String.valueOf(event.get("task_type"));
                            break;
                        case "final":
                            captureFinalAgentMeta(event, agentMeta[0]);
                            Object finalAnswer = event.get("answer");
                            if (finalAnswer != null && !String.valueOf(finalAnswer).isBlank()) {
                                // Keep persisted history aligned with the final response,
                                // never with intermediate multimodal/tool chunks.
                                answerBuilder.setLength(0);
                                answerBuilder.append(finalAnswer);
                            }
                            if (event.containsKey("task_type")) taskType[0] = String.valueOf(event.get("task_type"));
                            if (event.get("product_cards") instanceof java.util.List<?> pc) {
                                mergeProductCards(productCards[0], pc);
                            }
                            if (event.get("confirm_card") instanceof Map<?, ?> cc) {
                                confirmCard[0] = (Map<String, Object>) cc;
                            }
                            if (event.get("cart_selection") instanceof Map<?, ?> cs) {
                                cartSelection[0] = (Map<String, Object>) cs;
                            }
                            if (event.containsKey("sources")) {
                                try {
                                    sources[0] = objectMapper.writeValueAsString(event.get("sources"));
                                } catch (IOException ignored) { }
                            }
                            break;
                        case "error":
                            // ai-service 侧 DashScope 拒识别 / HEAD 预检失败会走这里
                            // (HTTP 400 情况已被 WebClient 转成 doOnError,这里主要是流内 error 帧)
                            log.warn("AI[MM] stream error: {}", event.getOrDefault("message", ""));
                            break;
                    }
                }).doOnComplete(() -> {
                    if (!finalized.compareAndSet(false, true)) return;
                    try {
                        String answer = answerBuilder.toString();
                        Message aiMsg = completeStreamingAssistant(
                                assistantMessageId.get(), answer, taskType[0], productCards[0],
                                confirmCard[0], cartSelection[0], sources[0], agentMeta[0]
                        );
                        ctxService.invalidateConversationContext(conversationId);
                        rollingSummaryService.scheduleUpdate(conversationId);
                        saveQaLog(userId, conversationId,
                                safeContent.isEmpty() ? "[图片]" : safeContent,
                                answer,
                                taskType[0].isEmpty() ? "shopping" : taskType[0],
                                System.currentTimeMillis() - streamStartMs);
                        emitter.send(SseEmitter.event().name("done").data(Map.of("messageId", aiMsg.getId())));
                        emitter.complete();
                    } catch (Exception e) {
                        log.error("SSE[MM] onComplete save failed", e);
                        try {
                            emitter.send(SseEmitter.event().name("error").data(Map.of("content", e.getMessage())));
                        } catch (IOException ex) { }
                        emitter.complete();
                    }
                }).doOnError(e -> {
                    if (!finalized.compareAndSet(false, true)) {
                        log.debug("Reactor[MM] doOnError but already finalized conv={}", conversationId);
                        return;
                    }
                    log.error("SSE[MM] stream error (ai-service upstream)", e);
                    String answer = answerBuilder.toString();
                    Long errId = persistTruncatedInternal(conversationId, assistantMessageId.get(), answer,
                            productCards[0], confirmCard[0], cartSelection[0],
                            taskType[0], STOP_SERVER);
                    try {
                        Map<String, Object> payload = new java.util.HashMap<>();
                        // 图片类错误(ai-service /assistant/multimodal/{run,stream} 返回 HTTP 400)会走到这里
                        // WebClient 抛的是 WebClientResponseException,e.getMessage() 里可能含
                        // "AI_MULTIMODAL_IMAGE_INVALID",前端据此展示"图片无法识别,请换一张"
                        payload.put("content", String.valueOf(e.getMessage()));
                        if (errId != null) payload.put("messageId", errId);
                        emitter.send(SseEmitter.event().name("error").data(payload));
                    } catch (IOException ex) { }
                    emitter.complete();
                }).doFinally(signal -> conversationTurnGuard.release(conversationId, turnId)).subscribe();
            } catch (Exception e) {
                log.error("SSE[MM] setup error", e);
                if (finalized.compareAndSet(false, true)) {
                    persistTruncatedInternal(conversationId, assistantMessageId.get(), "", null, null, null, "", STOP_SERVER);
                }
                try {
                    emitter.send(SseEmitter.event().name("error").data(Map.of("content", e.getMessage())));
                    emitter.complete();
                } catch (IOException ex) { emitter.completeWithError(ex); }
                conversationTurnGuard.release(conversationId, turnId);
            }
        });
        return emitter;
    }

    // ---------- 聊天图片上传 ----------
    /**
     * 上传聊天图片到对象存储。走 common-storage 的 StorageService(自动装配为 OSS 或本地磁盘)。
     * 校验规则:
     * <ul>
     *   <li>MIME 必须在 {@code chat-service.upload.image.allowed-mime} 白名单内</li>
     *   <li>大小 &le; {@code chat-service.upload.image.max-bytes}(默认 10MB)</li>
     * </ul>
     * 校验失败抛 {@link IllegalArgumentException},由全局异常处理转 400。
     */
    @Override public Map<String, Object> uploadChatImage(MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("上传文件为空");
        }
        // 1) 大小校验
        long size = file.getSize();
        if (size > imageMaxBytes) {
            throw new IllegalArgumentException(
                    "图片大小 " + size + " 字节超过上限 " + imageMaxBytes + " 字节");
        }
        // 2) MIME 校验:白名单精确匹配,拒绝 application/octet-stream 等模糊类型
        String contentType = file.getContentType();
        Set<String> allowed = new HashSet<>(Arrays.asList(imageAllowedMime.split(",")));
        // 白名单里都是 image/xxx 形式,做个 trim 防意外空格
        allowed.removeIf(String::isBlank);
        Set<String> normalized = new HashSet<>();
        for (String m : allowed) normalized.add(m.trim().toLowerCase());
        if (contentType == null || !normalized.contains(contentType.toLowerCase())) {
            throw new IllegalArgumentException("不支持的图片类型:" + contentType + ",允许:" + normalized);
        }
        // 3) 存 OSS
        String objectKey;
        String url;
        try {
            objectKey = storageService.put(file);
            url = storageService.getUrl(objectKey);
        } catch (RuntimeException ex) {
            log.error("[uploadChatImage] object storage upload failed, mime={}, size={}",
                    contentType, size, ex);
            throw new BizException("图片上传失败，请检查对象存储配置、写入权限和 Bucket 地域");
        }
        if (url.contains("localhost") || url.contains("127.0.0.1")) {
            throw new BizException("图片上传未启用可公开访问的对象存储，请配置 CLOUD_STORAGE_ACCESS_KEY、CLOUD_STORAGE_SECRET_KEY、CLOUD_STORAGE_BUCKET 和 CLOUD_STORAGE_DOMAIN");
        }
        log.info("[uploadChatImage] key={} url={} size={} mime={}", objectKey, url, size, contentType);
        Map<String, Object> res = new java.util.HashMap<>();
        res.put("objectKey", objectKey);
        res.put("url", url);
        return res;
    }

    // ---------- 反馈 ----------
    @Override public void submitFeedback(FeedbackRequest req) {
        Message msg = msgMapper.selectById(req.getMessageId());
        if (msg != null) {
            msg.setFeedbackType(req.getFeedbackType()); msg.setFeedbackTime(LocalDateTime.now());
            msgMapper.updateById(msg);
            // 同步 QaLog
            List<QaLog> logs = qaLogMapper.selectList(
                    new LambdaQueryWrapper<QaLog>().eq(QaLog::getConversationId, msg.getConversationId())
                            .orderByDesc(QaLog::getCreateTime).last("LIMIT 1"));
            if (!logs.isEmpty()) { QaLog l = logs.get(0); l.setFeedbackType(req.getFeedbackType()); l.setFeedbackTime(LocalDateTime.now()); qaLogMapper.updateById(l); }
        }
    }

    // ---------- 截断持久化（双保险：前端 POST + 后端 doOnCancel） ----------
    @Override @Transactional public Long persistTruncatedFromClient(Long userId, Long conversationId, String content,
                                                                     List<Map<String, Object>> productCards,
                                                                     Map<String, Object> confirmCard,
                                                                     Map<String, Object> cartSelection,
                                                                     String taskType, Long clientTs, String clientRequestId) {
        String turnId = normalizeProvidedTurnId(clientRequestId);
        Message assistant = turnId == null ? null : findAssistantByTurnId(conversationId, turnId);
        return persistTruncatedInternal(conversationId, assistant == null ? null : assistant.getId(), content,
                productCards, confirmCard, cartSelection, taskType, STOP_USER_ABORT);
    }

    /**
     * 截断消息落库,被前端 stop 接口与后端 Flux.doOnCancel 共用。
     * 去重策略:同 conversation + 同 content 前缀 + 60s 内已有 truncated 记录 → 跳过。
     * 返回新插入(或去重命中已存在)的 message id;content 为空时跳过(避免空消息)。
     */
    private Long persistTruncatedInternal(Long conversationId, Long assistantMessageId, String content,
                                          List<Map<String, Object>> productCards,
                                          Map<String, Object> confirmCard,
                                          Map<String, Object> cartSelection,
                                          String taskType, String stoppedReason) {
        log.info("[truncated] enter persistTruncatedInternal conv={} reason={} contentLen={}",
                conversationId, stoppedReason, content == null ? 0 : content.length());
        if (assistantMessageId != null) {
            try {
                Message assistant = msgMapper.selectById(assistantMessageId);
                if (assistant == null || !conversationId.equals(assistant.getConversationId())) {
                    return null;
                }
                if (content != null && !content.isEmpty()) assistant.setContent(content);
                assistant.setStatus(STATUS_TRUNCATED);
                assistant.setStoppedReason(stoppedReason);
                assistant.setStoppedAt(LocalDateTime.now());
                if (productCards != null && !productCards.isEmpty()) assistant.setProductCards(productCards);
                if (confirmCard != null) assistant.setConfirmCard(confirmCard);
                if (cartSelection != null) assistant.setCartSelection(cartSelection);
                if (taskType != null && !taskType.isEmpty()) assistant.setTaskType(taskType);
                msgMapper.updateById(assistant);
                ctxService.invalidateConversationContext(conversationId);
                return assistant.getId();
            } catch (Exception e) {
                log.error("[truncated] update streaming assistant failed conv={} messageId={}",
                        conversationId, assistantMessageId, e);
                return null;
            }
        }
        if (content == null || content.isEmpty()) {
            log.info("skip persist truncated: empty content conv={}", conversationId);
            return null;
        }
        try {
            String prefix = content.length() > 32 ? content.substring(0, 32) : content;
            // 在 Java 端拼好 LIKE pattern,避免 PG 推断 CONCAT(?) 参数类型失败
            String contentLike = prefix + "%";
            Message dup = msgMapper.selectRecentTruncated(conversationId, contentLike, TRUNC_DEDUP_SECONDS);
            if (dup != null) {
                log.info("truncated dedup hit, skip insert conv={} existingId={}", conversationId, dup.getId());
                return dup.getId();
            }
            Message aiMsg = new Message();
            aiMsg.setConversationId(conversationId);
            aiMsg.setRole("assistant");
            aiMsg.setContent(content);
            aiMsg.setMessageType("text");
            aiMsg.setTaskType(taskType == null || taskType.isEmpty() ? "shopping" : taskType);
            aiMsg.setStatus(STATUS_TRUNCATED);
            aiMsg.setStoppedReason(stoppedReason);
            aiMsg.setStoppedAt(LocalDateTime.now());
            if (productCards != null && !productCards.isEmpty()) aiMsg.setProductCards(productCards);
            if (confirmCard != null) aiMsg.setConfirmCard(confirmCard);
            if (cartSelection != null) aiMsg.setCartSelection(cartSelection);
            aiMsg.setCreateTime(LocalDateTime.now());
            log.info("[truncated] before insert conv={} contentLen={}", conversationId, content.length());
            msgMapper.insert(aiMsg);
            log.info("persisted truncated assistant conv={} id={} reason={} len={}",
                    conversationId, aiMsg.getId(), stoppedReason, content.length());
            return aiMsg.getId();
        } catch (Exception e) {
            // 任何异常都吞掉并打日志,避免中断 SseEmitter 回调线程
            log.error("[truncated] persist failed conv={} reason={}", conversationId, stoppedReason, e);
            return null;
        }
    }

    // ---------- 私有 ----------
    /** Legacy non-stream endpoint compatibility. SSE turns use turnId + conversation lock instead. */
    private boolean isDuplicate(Long convId, String content) {
        String key = DEDUP_PREFIX + convId + ":" + (content == null ? 0 : content.hashCode());
        Boolean accepted = redisTemplate.opsForValue().setIfAbsent(key, "1", Duration.ofSeconds(dedupWindow));
        return Boolean.FALSE.equals(accepted);
    }

    private Message saveUserMessage(Long convId, String content) {
        return saveUserMessage(convId, content, null, null);
    }
    /**
     * 落库 user 消息。imageUrl 非空 → message_type=multimodal_image + image_url 写入;
     * 否则走原有 message_type=text 逻辑。允许 content 为空(纯图搜索场景),此时
     * content 落成占位符方便 UI 渲染。
     */
    private Message saveUserMessage(Long convId, String content, String imageUrl, String turnId) {
        Message m = new Message();
        m.setConversationId(convId);
        m.setRole("user");
        m.setTurnId(turnId);
        String safeContent = content != null ? content : "";
        boolean hasImage = imageUrl != null && !imageUrl.isEmpty();
        if (safeContent.isEmpty() && hasImage) {
            // 纯图搜索:用占位符方便消息列表 UI 显示"[图片]"
            safeContent = "[图片]";
        }
        m.setContent(safeContent);
        m.setMessageType(hasImage ? MSG_TYPE_MULTIMODAL_IMAGE : MSG_TYPE_TEXT);
        if (hasImage) m.setImageUrl(imageUrl);
        m.setCreateTime(LocalDateTime.now());
        msgMapper.insert(m);
        return m;
    }

    private Message createStreamingAssistant(Long conversationId, String turnId) {
        Message assistant = new Message();
        assistant.setConversationId(conversationId);
        assistant.setTurnId(turnId);
        assistant.setRole("assistant");
        assistant.setContent("");
        assistant.setMessageType(MSG_TYPE_TEXT);
        assistant.setStatus("streaming");
        assistant.setCreateTime(LocalDateTime.now());
        msgMapper.insert(assistant);
        return assistant;
    }

    /**
     * Establishes replacement only after the new assistant row exists. The
     * next AI request is built afterwards, so it cannot see the superseded
     * answer in either raw history or the rolling summary.
     */
    private void applyRegenerationReplacement(Long conversationId, boolean retry,
                                              Long replacedAssistantMessageId,
                                              Long replacementAssistantMessageId) {
        if (!retry || replacedAssistantMessageId == null || replacementAssistantMessageId == null) {
            return;
        }
        if (replacedAssistantMessageId.equals(replacementAssistantMessageId)) {
            throw new IllegalArgumentException("replacement assistant message must differ from original");
        }
        int updated = msgMapper.markAssistantSuperseded(
                conversationId, replacedAssistantMessageId, replacementAssistantMessageId);
        if (updated != 1) {
            throw new IllegalArgumentException("original assistant message is unavailable for regeneration");
        }
        ctxService.resetRollingSummaryForRegeneration(conversationId);
        log.info("regeneration replacement applied conv={} oldMessageId={} newMessageId={}",
                conversationId, replacedAssistantMessageId, replacementAssistantMessageId);
    }

    private void validateRegenerationTarget(Long conversationId, boolean retry,
                                            Long replacedAssistantMessageId) {
        if (!retry || replacedAssistantMessageId == null) return;
        Message original = msgMapper.selectById(replacedAssistantMessageId);
        if (original == null
                || !conversationId.equals(original.getConversationId())
                || !"assistant".equals(original.getRole())
                || original.getSupersededByMessageId() != null) {
            throw new IllegalArgumentException("original assistant message is unavailable for regeneration");
        }
    }

    private Message completeStreamingAssistant(Long assistantMessageId, String answer, String taskType,
                                                List<Map<String, Object>> productCards,
                                                Map<String, Object> confirmCard,
                                                Map<String, Object> cartSelection,
                                                String sources, Map<String, Object> agentMeta) {
        if (assistantMessageId == null) {
            throw new IllegalStateException("streaming assistant message is missing");
        }
        Message assistant = msgMapper.selectById(assistantMessageId);
        if (assistant == null) {
            throw new IllegalStateException("streaming assistant message does not exist: " + assistantMessageId);
        }
        assistant.setContent(answer == null || answer.isEmpty() ? "AI 暂时无法回复,请稍后再试" : answer);
        assistant.setMessageType(MSG_TYPE_TEXT);
        assistant.setTaskType(taskType == null || taskType.isEmpty() ? "shopping" : taskType);
        assistant.setStatus(STATUS_DONE);
        assistant.setStoppedReason(null);
        assistant.setStoppedAt(null);
        if (productCards != null && !productCards.isEmpty()) assistant.setProductCards(productCards);
        if (confirmCard != null) assistant.setConfirmCard(confirmCard);
        if (cartSelection != null) assistant.setCartSelection(cartSelection);
        assistant.setSources(sources == null || sources.isEmpty() ? null : sources);
        if (agentMeta != null && !agentMeta.isEmpty()) assistant.setAgentMeta(agentMeta);
        msgMapper.updateById(assistant);
        return assistant;
    }

    private Message findAssistantByTurnId(Long conversationId, String turnId) {
        if (conversationId == null || turnId == null || turnId.isBlank()) return null;
        return msgMapper.selectOne(new LambdaQueryWrapper<Message>()
                .eq(Message::getConversationId, conversationId)
                .eq(Message::getTurnId, turnId)
                .eq(Message::getRole, "assistant")
                .last("LIMIT 1"));
    }

    private SseEmitter rejectedTurnEmitter(Long conversationId, String turnId) {
        SseEmitter emitter = new SseEmitter(sseTimeout);
        String code = conversationTurnGuard.isOwnedBy(conversationId, turnId)
                ? "CHAT_REQUEST_IN_PROGRESS" : "CHAT_CONVERSATION_BUSY";
        String message = "CHAT_REQUEST_IN_PROGRESS".equals(code)
                ? "相同请求正在处理中，请勿重复提交"
                : "当前会话正在回复，请等待完成后继续发送";
        try {
            emitter.send(SseEmitter.event().name("error").data(Map.of("code", code, "message", message)));
        } catch (IOException ignored) {
            // The caller has already gone away; there is no server-side turn to clean up.
        }
        emitter.complete();
        return emitter;
    }

    private void replayExistingTurn(SseEmitter emitter, Message assistant) {
        try {
            if ("streaming".equals(assistant.getStatus())) {
                emitter.send(SseEmitter.event().name("error").data(Map.of(
                        "code", "CHAT_REQUEST_IN_PROGRESS", "message", "相同请求正在处理中，请勿重复提交"
                )));
            } else {
                Map<String, Object> finalPayload = new java.util.LinkedHashMap<>();
                finalPayload.put("answer", assistant.getContent());
                finalPayload.put("task_type", assistant.getTaskType());
                finalPayload.put("product_cards", assistant.getProductCards() == null ? List.of() : assistant.getProductCards());
                finalPayload.put("confirm_card", assistant.getConfirmCard());
                finalPayload.put("cart_selection", assistant.getCartSelection());
                emitter.send(SseEmitter.event().name("final").data(objectMapper.writeValueAsString(finalPayload)));
                emitter.send(SseEmitter.event().name("done").data(Map.of("messageId", assistant.getId())));
            }
        } catch (Exception e) {
            log.warn("existing turn replay failed messageId={}: {}", assistant.getId(), e.getMessage());
        } finally {
            emitter.complete();
        }
    }

    private static String normalizeTurnId(String clientRequestId) {
        String provided = normalizeProvidedTurnId(clientRequestId);
        return provided == null ? java.util.UUID.randomUUID().toString() : provided;
    }

    private static String normalizeProvidedTurnId(String clientRequestId) {
        if (clientRequestId == null) return null;
        String value = clientRequestId.trim();
        return value.isEmpty() ? null : value.substring(0, Math.min(64, value.length()));
    }
    private boolean isFirstMessage(Long convId) {
        return msgMapper.selectCount(new LambdaQueryWrapper<Message>()
                .eq(Message::getConversationId, convId)) <= 1;
    }
    @SuppressWarnings("unchecked")
    private static void captureOrchestratorMeta(String eventType, Map<String, Object> event,
                                                Map<String, Object> agentMeta) {
        if ("orchestrator_plan".equals(eventType)) {
            agentMeta.put("orchestratorMode", event.getOrDefault("mode", "complex"));
            agentMeta.put("orchestratorReason", event.get("reason"));
            agentMeta.put("subQuestions", event.getOrDefault("tasks", List.of()));
            return;
        }
        List<Map<String, Object>> subtasks = (List<Map<String, Object>>) agentMeta.computeIfAbsent(
                "subtaskEvents", ignored -> new java.util.ArrayList<Map<String, Object>>());
        subtasks.add(new java.util.LinkedHashMap<>(event));
    }

    /**
     * Build the one raw suffix that accompanies the persisted summary.
     *
     * <p>When summary is enabled and available, this returns every visible
     * message after its coverage point.  Normally that is the configured
     * four-message keep window; while an async summary is pending or failed it
     * may be longer.  That fallback is deliberate: no visible message may be
     * removed from the model context before a summary has actually persisted.</p>
     */
    private List<Map<String, Object>> buildConversationHistory(Long conversationId) {
        var summaryContext = rollingSummaryEnabled
                ? ctxService.getRollingSummaryContext(conversationId)
                : null;
        Long coveredMessageId = summaryContext != null
                && summaryContext.getSummary() != null
                && !summaryContext.getSummary().isBlank()
                ? summaryContext.getSummaryCoveredMessageId()
                : null;
        List<Message> messages = msgMapper.selectVisibleMessagesAfter(conversationId, coveredMessageId);
        List<Map<String, Object>> history = new java.util.ArrayList<>();
        for (Message message : messages) {
            Map<String, Object> item = new java.util.LinkedHashMap<>();
            item.put("id", message.getId());
            item.put("role", message.getRole());
            item.put("content", message.getContent());
            item.put("image_url", message.getImageUrl());
            item.put("product_cards", message.getProductCards());
            item.put("task_type", message.getTaskType());
            item.put("agent_meta", message.getAgentMeta());
            history.add(item);
        }
        return history;
    }

    /**
     * The Router and ChitchatAgent receive this same persisted summary through
     * the assistant request.  Raw messages remain in chat_svc.message; this
     * method never treats Redis as the source of summary truth.
     */
    private String buildConversationSummary(Long conversationId) {
        if (!rollingSummaryEnabled) return "";
        var context = ctxService.getRollingSummaryContext(conversationId);
        return context == null || context.getSummary() == null ? "" : context.getSummary();
    }

    private static void captureFinalAgentMeta(Map<String, Object> event, Map<String, Object> agentMeta) {
        if (!isComplexTask(String.valueOf(event.getOrDefault("task_type", "")))) return;
        agentMeta.put("orchestratorMode", event.getOrDefault("orchestrator_mode", "complex"));
        agentMeta.put("orchestratorReason", event.get("orchestrator_reason"));
        agentMeta.put("subQuestions", event.getOrDefault("sub_questions", List.of()));
        agentMeta.put("subResults", event.getOrDefault("sub_results", List.of()));
        agentMeta.put("taskLevels", event.getOrDefault("task_levels", List.of()));
    }

    /**
     * ``orchestrator`` is the legacy internal node label.  New AI Service
     * responses expose the Router semantic result as ``complex`` instead.
     */
    private static boolean isComplexTask(String taskType) {
        return "complex".equals(taskType) || "orchestrator".equals(taskType);
    }

    /**
     * Accumulate a completed complex-task segment for persistence.  The same
     * event has already been forwarded to H5; this method only ensures that a
     * normal completion or an interrupted stream can replay what the user saw.
     */
    @SuppressWarnings("unchecked")
    private static void captureSubtaskResult(Map<String, Object> event,
                                             StringBuilder answerBuilder,
                                             java.util.List<Map<String, Object>> productCards) {
        String answer = String.valueOf(event.getOrDefault("answer", "")).trim();
        if (!answer.isEmpty()) {
            if (answerBuilder.length() > 0) answerBuilder.append("\n\n");
            answerBuilder.append(answer);
        }
        Object cards = event.get("product_cards");
        if (!(cards instanceof java.util.List<?>)) cards = event.get("productCards");
        if (cards instanceof java.util.List<?> list) {
            mergeProductCards(productCards, list);
        }
    }

    @SuppressWarnings("unchecked")
    private static void mergeProductCards(java.util.List<Map<String, Object>> target,
                                          java.util.List<?> incoming) {
        java.util.Set<String> seen = new java.util.LinkedHashSet<>();
        for (Map<String, Object> card : target) {
            seen.add(productCardKey(card));
        }
        for (Object item : incoming) {
            if (!(item instanceof Map<?, ?> raw)) continue;
            Map<String, Object> card = new java.util.LinkedHashMap<>((Map<String, Object>) raw);
            String key = productCardKey(card);
            if (!key.isEmpty() && !seen.add(key)) continue;
            target.add(card);
        }
    }

    private static String productCardKey(Map<String, Object> card) {
        Object id = card.get("product_id");
        if (id == null) id = card.get("productId");
        if (id == null) id = card.get("id");
        if (id == null) id = card.get("title");
        return id == null ? "" : String.valueOf(id);
    }

    private void saveQaLog(Long userId, Long convId, String question, String answer, String taskType, long duration) {
        QaLog log = new QaLog();
        log.setUserId(userId); log.setConversationId(convId);
        log.setQuestion(question); log.setAnswer(answer);
        log.setTaskType(taskType); log.setDurationMs(duration);
        log.setCreateTime(LocalDateTime.now());
        qaLogMapper.insert(log);
    }
}

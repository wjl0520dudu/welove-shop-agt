package com.welove.shop.chat.service.impl;

import com.welove.shop.chat.entity.ConversationContext;
import com.welove.shop.chat.entity.Message;
import com.welove.shop.chat.mapper.MessageMapper;
import com.welove.shop.chat.service.ConversationContextService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Maintains the one persisted rolling summary for a conversation.
 *
 * <p>Messages stay authoritative in {@code chat_svc.message}.  This service
 * only rolls the prefix that is older than the recent verbatim window, then
 * asks ai-service to merge that prefix into the existing summary.  It is
 * intentionally asynchronous: neither the user SSE stream nor assistant
 * message persistence waits for an extra LLM call.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RollingConversationSummaryService {
    private final MessageMapper messageMapper;
    private final ConversationContextService contextService;
    private final RestTemplate restTemplate;

    @Value("${ai.service.url}")
    private String aiUrl;

    @Value("${chat-service.context.rolling-summary.enabled:true}")
    private boolean enabled;

    /** Equivalent to SummarizationMiddleware(trigger=("messages", 20)). */
    @Value("${chat-service.context.rolling-summary.trigger-message-count:20}")
    private int triggerMessageCount;

    /** Equivalent to SummarizationMiddleware(keep=("messages", 4)). */
    @Value("${chat-service.context.rolling-summary.keep-message-count:4}")
    private int keepMessageCount;

    @Value("${chat-service.context.rolling-summary.max-chars:1600}")
    private int maxSummaryChars;

    /** Queue a best-effort update after an assistant message has been saved. */
    @Async
    @SuppressWarnings("unchecked")
    public void scheduleUpdate(Long conversationId) {
        if (!enabled || conversationId == null) {
            return;
        }
        try {
            ConversationContext context = contextService.getRollingSummaryContext(conversationId);
            Long coveredMessageId = context == null ? null : context.getSummaryCoveredMessageId();
            Long checkpointMessageId = context == null ? null : context.getSummaryCheckpointMessageId();

            // Count only complete visible messages added after the prior batch
            // checkpoint.  Keeping the newest four messages therefore does not
            // turn the next ten-turn batch into an eight-turn batch.
            List<Message> messagesSinceCheckpoint = messageMapper.selectVisibleMessagesAfter(
                    conversationId, checkpointMessageId);
            if (messagesSinceCheckpoint.size() < Math.max(2, triggerMessageCount)) {
                return;
            }

            Long targetMessageId = messageMapper.selectSummaryTargetMessageId(
                    conversationId, Math.max(0, keepMessageCount));
            if (targetMessageId == null || (coveredMessageId != null && coveredMessageId >= targetMessageId)) {
                return;
            }

            List<Message> newlyEligible = messageMapper.selectMessagesForRollingSummary(
                    conversationId, coveredMessageId, targetMessageId);
            if (newlyEligible.isEmpty()) return;
            Long currentCheckpointId = messagesSinceCheckpoint.get(messagesSinceCheckpoint.size() - 1).getId();
            if (currentCheckpointId == null) return;

            Map<String, Object> body = new LinkedHashMap<>();
            body.put("previous_summary", context == null ? "" : safe(context.getSummary()));
            body.put("messages", toSummaryMessages(newlyEligible));
            body.put("max_chars", Math.max(200, maxSummaryChars));

            Map<String, Object> response = restTemplate.postForObject(
                    aiUrl + "/assistant/conversation-summary", body, Map.class);
            String summary = response == null ? "" : safe(response.get("summary"));
            if (summary.isBlank()) {
                log.warn("rolling summary returned empty conv={}", conversationId);
                return;
            }

            boolean updated = contextService.updateRollingSummary(
                    conversationId, summary, targetMessageId, currentCheckpointId);
            log.info("rolling summary {} conv={} coveredMessageId={} checkpointMessageId={} summarizedMessages={} triggerMessages={} keepMessages={}",
                    updated ? "updated" : "skipped", conversationId, targetMessageId,
                    currentCheckpointId, newlyEligible.size(), triggerMessageCount, keepMessageCount);
        } catch (Exception e) {
            // Summary is an optimization. The next request carries the whole
            // not-yet-covered raw suffix, and a later completed turn retries.
            log.warn("rolling summary update failed conv={}: {}", conversationId, e.getMessage());
        }
    }

    private static List<Map<String, Object>> toSummaryMessages(List<Message> messages) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Message message : messages) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", message.getId());
            item.put("role", message.getRole());
            item.put("content", safe(message.getContent()));
            if (message.getImageUrl() != null && !message.getImageUrl().isBlank()) {
                item.put("image_url", message.getImageUrl());
            }
            if (message.getProductCards() != null && !message.getProductCards().isEmpty()) {
                item.put("product_cards", message.getProductCards());
            }
            out.add(item);
        }
        return out;
    }

    private static String safe(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }
}

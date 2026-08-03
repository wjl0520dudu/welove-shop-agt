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

    @Value("${chat-service.context.rolling-summary.recent-message-window:10}")
    private int recentMessageWindow;

    @Value("${chat-service.context.rolling-summary.turn-threshold:4}")
    private int turnThreshold;

    @Value("${chat-service.context.rolling-summary.char-threshold:4000}")
    private int charThreshold;

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
            Long targetMessageId = messageMapper.selectSummaryTargetMessageId(
                    conversationId, Math.max(1, recentMessageWindow));
            if (targetMessageId == null) {
                return;
            }

            ConversationContext context = contextService.getRollingSummaryContext(conversationId);
            Long coveredMessageId = context == null ? null : context.getSummaryCoveredMessageId();
            if (coveredMessageId != null && coveredMessageId >= targetMessageId) {
                return;
            }

            List<Message> newlyEligible = messageMapper.selectMessagesForRollingSummary(
                    conversationId, coveredMessageId, targetMessageId);
            if (newlyEligible.isEmpty()) {
                return;
            }

            int textLength = newlyEligible.stream()
                    .map(Message::getContent)
                    .filter(java.util.Objects::nonNull)
                    .mapToInt(String::length)
                    .sum();
            // A turn means one user message plus one assistant message.  We
            // wait until there is meaningful new material unless the text is
            // already long, avoiding an LLM call after every short turn.
            if (newlyEligible.size() < Math.max(1, turnThreshold) * 2
                    && textLength < Math.max(1, charThreshold)) {
                return;
            }

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
                    conversationId, summary, targetMessageId);
            log.info("rolling summary {} conv={} coveredMessageId={} newMessages={} chars={}",
                    updated ? "updated" : "skipped", conversationId, targetMessageId,
                    newlyEligible.size(), textLength);
        } catch (Exception e) {
            // Summary is an optimization.  The next request still carries the
            // recent verbatim window, and a later completed turn retries this.
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

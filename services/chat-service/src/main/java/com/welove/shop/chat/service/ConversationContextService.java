package com.welove.shop.chat.service;

import com.welove.shop.chat.entity.Message;
import com.welove.shop.chat.entity.ConversationContext;
import java.util.List;

public interface ConversationContextService {
    List<Message> getConversationContext(Long conversationId, int maxMessages);
    void updateConversationContext(Long conversationId, Long userId, Message newMessage);
    void invalidateConversationContext(Long conversationId);
    ConversationContext getRollingSummaryContext(Long conversationId);
    boolean updateRollingSummary(Long conversationId, String summary, Long coveredMessageId,
                                 Long checkpointMessageId);
    void cleanupExpiredContexts(int days);
}

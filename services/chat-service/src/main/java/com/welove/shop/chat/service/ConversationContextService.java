package com.welove.shop.chat.service;

import com.welove.shop.chat.entity.Message;
import java.util.List;

public interface ConversationContextService {
    List<Message> getConversationContext(Long conversationId, int maxMessages);
    void updateConversationContext(Long conversationId, Long userId, Message newMessage);
    void invalidateConversationContext(Long conversationId);
    void cleanupExpiredContexts(int days);
}

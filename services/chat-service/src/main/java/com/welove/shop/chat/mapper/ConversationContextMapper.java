package com.welove.shop.chat.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.welove.shop.chat.entity.ConversationContext;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface ConversationContextMapper extends BaseMapper<ConversationContext> {

    /**
     * Records that a conversation received a new visible message.
     *
     * <p>There is one persistent context record per conversation.  The chat
     * stream can receive consecutive turns before Redis is repopulated, so a
     * read-then-insert sequence is not safe here. PostgreSQL performs the
     * insert/update atomically under the conversation_id unique index.</p>
     */
    @Insert("""
            INSERT INTO conversation_context
                (conversation_id, user_id, window_size, importance_score, update_time, create_time)
            VALUES
                (#{context.conversationId}, #{context.userId}, #{context.windowSize},
                 #{context.importanceScore}, #{context.updateTime}, #{context.createTime})
            ON CONFLICT (conversation_id) WHERE conversation_id IS NOT NULL DO UPDATE
            SET user_id = EXCLUDED.user_id,
                window_size = EXCLUDED.window_size,
                importance_score = EXCLUDED.importance_score,
                update_time = EXCLUDED.update_time
            """)
    int upsertActivity(@Param("context") ConversationContext context);
}

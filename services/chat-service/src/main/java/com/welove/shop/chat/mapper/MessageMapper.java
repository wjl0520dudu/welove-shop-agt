package com.welove.shop.chat.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.welove.shop.chat.entity.Message;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface MessageMapper extends BaseMapper<Message> {

    /**
     * Finds the final message that may be rolled into a summary while keeping
     * the newest configured window verbatim for the Router and ChitchatAgent.
     */
    @Select("""
        SELECT id FROM chat_svc.message
        WHERE conversation_id = #{conversationId}
          AND role IN ('user', 'assistant')
          AND (status IS NULL OR status = 'done')
        ORDER BY id DESC
        OFFSET #{recentWindow}
        LIMIT 1
        """)
    Long selectSummaryTargetMessageId(@Param("conversationId") Long conversationId,
                                      @Param("recentWindow") int recentWindow);

    /** Returns newly eligible visible messages in chronological order. */
    @Select("""
        SELECT * FROM chat_svc.message
        WHERE conversation_id = #{conversationId}
          AND id > COALESCE(#{afterMessageId}, 0)
          AND id <= #{throughMessageId}
          AND role IN ('user', 'assistant')
          AND (status IS NULL OR status = 'done')
        ORDER BY id ASC
        """)
    List<Message> selectMessagesForRollingSummary(
            @Param("conversationId") Long conversationId,
            @Param("afterMessageId") Long afterMessageId,
            @Param("throughMessageId") Long throughMessageId);

    /** Visible messages after a persisted summary coverage point, ordered by time. */
    @Select("""
        SELECT * FROM chat_svc.message
        WHERE conversation_id = #{conversationId}
          AND id > COALESCE(#{afterMessageId}, 0)
          AND role IN ('user', 'assistant')
          AND (status IS NULL OR status = 'done')
        ORDER BY id ASC
        """)
    List<Message> selectVisibleMessagesAfter(
            @Param("conversationId") Long conversationId,
            @Param("afterMessageId") Long afterMessageId);

    /**
     * 去重查询:同一 conversation 下,近 N 秒内 status='truncated' 且内容前缀匹配的截断消息。
     * 用于双保险(前端 POST + 后端 doOnCancel)时避免同一条截断被写入两次。
     * 用 LIKE 前缀匹配即可,因为流式中断时两端持有的 content 应是同一前缀。
     */
    @Select("""
        SELECT * FROM chat_svc.message
        WHERE conversation_id = #{conversationId}
          AND status = 'truncated'
          AND content LIKE #{contentLike}
          AND stopped_at >= NOW() - CAST(#{sinceSeconds} || ' seconds' AS interval)
        ORDER BY id DESC
        LIMIT 1
        """)
    Message selectRecentTruncated(@Param("conversationId") Long conversationId,
                                  @Param("contentLike") String contentLike,
                                  @Param("sinceSeconds") int sinceSeconds);

    /**
     * 包装为 List 返回,符合 BaseMapper 风格的 collection 语义,避免单对象判空的歧义。
     */
    default java.util.List<Message> selectRecentTruncatedAsList(Long conversationId, String contentPrefix, int sinceSeconds) {
        Message m = selectRecentTruncated(conversationId, contentPrefix, sinceSeconds);
        return m == null ? java.util.Collections.emptyList() : java.util.List.of(m);
    }
}

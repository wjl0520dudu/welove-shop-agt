package com.welove.shop.chat.dto;

import lombok.Data;

import java.io.Serial;
import java.io.Serializable;
import java.util.List;
import java.util.Map;

/**
 * 前端在 AbortController 触发时主动把当前 assistant 半成品发到后端的请求体。
 * 后端会落库一条 status='truncated' 的 assistant 消息,刷新/切回会话仍能看到截断内容。
 *
 * 字段值均取自前端 abort 那一瞬已收到的 SSE 事件累加值。
 */
@Data
public class StopMessageRequest implements Serializable {
    @Serial private static final long serialVersionUID = 1L;

    private Long conversationId;
    /** 已收到的 token 拼接,可能为空(用户刚按下停止还没收到任何 token)。 */
    private String content;
    /** 已收到的产品卡列表(若 assistant 流中已发出 product_cards 事件)。 */
    private List<Map<String, Object>> productCards;
    private Map<String, Object> confirmCard;
    private Map<String, Object> cartSelection;
    private String taskType;
    /** Matches StreamChatRequest.clientRequestId so an interrupted turn updates its own assistant message. */
    private String clientRequestId;
    /** 客户端发起 stop 的 unix 毫秒时间戳,用于和后端 doOnCancel 落库做时序对照。 */
    private Long clientTs;
}

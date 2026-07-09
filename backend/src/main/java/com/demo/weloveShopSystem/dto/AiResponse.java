package com.demo.weloveShopSystem.dto;

import lombok.Data;
import java.util.List;
import java.util.Map;

/**
 * AI 服务返回结果的统一包装对象。
 */
@Data
public class AiResponse {
    /** AI 生成的文本回答。 */
    private String answer;
    /** 回答引用的资料来源，结构由 Python AI 服务返回决定。 */
    private List<Map<String, Object>> sources;
    /** 任务类型，例如商品推荐、知识问答、闲聊或购物车操作。 */
    private String taskType;
    /** 推荐商品卡片列表。 */
    private List<Map<String, Object>> productCards;
    /** 需要用户确认的操作卡片，例如删除购物车或修改购物车。 */
    private Map<String, Object> confirmCard;
    /** 购物车商品选择卡片。 */
    private Map<String, Object> cartSelection;
    /** 购物车列表卡片。 */
    private Map<String, Object> cartList;
    /** Python Agent 运行 ID。 */
    private String runId;
    /** Python Agent 链路追踪 ID。 */
    private String traceId;
    /** Python 侧是否返回错误。 */
    private Boolean error;
    /** Python 侧稳定错误码。 */
    private String errorCode;
    /** Python 侧错误或状态消息。 */
    private String message;
}

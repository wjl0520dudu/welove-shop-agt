package com.demo.weloveShopSystem.service;


import com.demo.weloveShopSystem.dto.AiResponse;

/**
 * AI 服务调用接口。
 */
public interface AiService {
    /** 请求 AI 服务解析知识库文档并建立索引。 */
    void parseDocument(String filePath, Long docId);

    /**
     * 根据问题和上下文生成 AI 回答。
     *
     * @param question 用户问题
     * @param context  相关上下文
     * @param userId   用户 ID
     * @return AI 回答对象
     */
    AiResponse ask(String question, String context, Long userId);

    /**
     * 根据用户问题生成会话标题并更新数据库。
     */
    void generateTitle(Long conversationId, String question);

    /** 删除指定文档的向量索引。 */
    void deleteDoc(Long docId);

    /**
     * 管理端 AI 助手问答。
     *
     * @param question 管理员问题
     * @param context  对话上下文
     * @param adminId  管理员 ID
     * @return AI 服务返回的结果 Map
     */
    java.util.Map<String, Object> askForAdmin(String question, String context, Long adminId);
}

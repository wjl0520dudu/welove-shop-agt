package com.demo.weloveShopSystem.controller.admin;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Conversation;
import com.demo.weloveShopSystem.entity.Message;
import com.demo.weloveShopSystem.mapper.ConversationMapper;
import com.demo.weloveShopSystem.mapper.MessageMapper;
import com.demo.weloveShopSystem.service.AiService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 后台管理员 AI 助手控制器。
 * <p>
 * 管理员和 AI 之间的问答会话独立走 scene=admin_chat,与 C 端会话隔离,
 * 避免管理员日常问答污染用户端画像与统计。挂在 /api/admin-chat 是历史习惯,
 * 不放在 /api/admin/** 下,因此需要额外在 SecurityConfig 里手动收口。
 */
@RestController
@RequestMapping("/api/admin-chat")
@RequiredArgsConstructor
@Slf4j
public class AdminChatController {

    private final AiService aiService;
    private final ConversationMapper conversationMapper;
    private final MessageMapper messageMapper;

    /** 新建管理员助手会话。 */
    @PostMapping("/conversations")
    public Result<Conversation> createConversation(
            @RequestParam Long adminId,
            @RequestParam(defaultValue = "新对话") String title) {
        Conversation conv = new Conversation();
        conv.setUserId(adminId);
        conv.setTitle(title);
        conv.setScene("admin_chat");
        conv.setIsPinned(false);
        conv.setCreateTime(LocalDateTime.now());
        conv.setUpdateTime(LocalDateTime.now());
        conversationMapper.insert(conv);
        log.info("[AdminChat] Created conversation: id={}, adminId={}", conv.getId(), adminId);
        return Result.success(conv);
    }

    /** 查询指定管理员在 admin_chat 场景下的会话列表,置顶优先、更新时间倒序。 */
    @GetMapping("/conversations")
    public Result<List<Conversation>> getConversations(@RequestParam Long adminId) {
        List<Conversation> list = conversationMapper.selectList(
                new LambdaQueryWrapper<Conversation>()
                        .eq(Conversation::getUserId, adminId)
                        .eq(Conversation::getScene, "admin_chat")
                        .orderByDesc(Conversation::getIsPinned)
                        .orderByDesc(Conversation::getUpdateTime));
        return Result.success(list);
    }

    /** 更新会话标题或置顶状态,body 里传什么就改什么,不传保持原值。 */
    @PutMapping("/conversations/{id}")
    public Result<String> updateConversation(
            @PathVariable Long id,
            @RequestBody Map<String, Object> body) {
        Conversation conv = conversationMapper.selectById(id);
        if (conv == null) {
            return Result.error("对话不存在");
        }
        if (body.containsKey("title")) {
            conv.setTitle((String) body.get("title"));
        }
        if (body.containsKey("isPinned")) {
            conv.setIsPinned((Boolean) body.get("isPinned"));
        }
        conv.setUpdateTime(LocalDateTime.now());
        conversationMapper.updateById(conv);
        return Result.success("ok");
    }

    /** 删除会话及其全部消息,不做软删。 */
    @DeleteMapping("/conversations/{id}")
    public Result<String> deleteConversation(@PathVariable Long id) {
        messageMapper.delete(new LambdaQueryWrapper<Message>()
                .eq(Message::getConversationId, id));
        conversationMapper.deleteById(id);
        return Result.success("ok");
    }

    /** 按时间正序返回会话消息列表。 */
    @GetMapping("/messages")
    public Result<List<Message>> getMessages(@RequestParam Long conversationId) {
        List<Message> messages = messageMapper.selectList(
                new LambdaQueryWrapper<Message>()
                        .eq(Message::getConversationId, conversationId)
                        .orderByAsc(Message::getCreateTime));
        return Result.success(messages);
    }

    /**
     * 发送管理员消息并同步获取 AI 回复,一次写两条 message 记录(user + assistant)。
     * <p>
     * 首次发言且会话标题为默认 "对话 XXX" 时,取消息内容前 20 字作为标题,
     * 让会话列表更好识别。
     */
    @PostMapping("/messages")
    public Result<Message> sendMessage(
            @RequestParam Long adminId,
            @RequestParam Long conversationId,
            @RequestBody Map<String, String> body) {
        String content = body.get("content");
        if (content == null || content.trim().isEmpty()) {
            return Result.error("消息内容不能为空");
        }

        Message userMsg = new Message();
        userMsg.setConversationId(conversationId);
        userMsg.setRole("user");
        userMsg.setContent(content);
        userMsg.setCreateTime(LocalDateTime.now());
        messageMapper.insert(userMsg);

        Conversation conv = conversationMapper.selectById(conversationId);
        if (conv != null) {
            conv.setUpdateTime(LocalDateTime.now());
            if (conv.getTitle() == null || conv.getTitle().startsWith("对话 ")) {
                String shortTitle = content.length() > 20 ? content.substring(0, 20) + "..." : content;
                conv.setTitle(shortTitle);
            }
            conversationMapper.updateById(conv);
        }

        Map<String, Object> aiResult = aiService.askForAdmin(content, "", adminId);
        String answer = (String) aiResult.getOrDefault("answer", "抱歉,服务暂时不可用。");
        String taskType = (String) aiResult.getOrDefault("task_type", "admin_copilot");

        Message aiMsg = new Message();
        aiMsg.setConversationId(conversationId);
        aiMsg.setRole("assistant");
        aiMsg.setContent(answer);
        aiMsg.setTaskType(taskType);
        aiMsg.setCreateTime(LocalDateTime.now());
        Object sources = aiResult.get("sources");
        if (sources != null) {
            aiMsg.setSources(sources.toString());
        }
        messageMapper.insert(aiMsg);

        log.info("[AdminChat] Message sent: convId={}, answerLen={}, taskType={}",
                conversationId, answer.length(), taskType);
        return Result.success(aiMsg);
    }

    /** 提交某条 assistant 消息的正负反馈,记录 feedbackType 与时间戳。 */
    @PostMapping("/messages/feedback")
    public Result<String> submitFeedback(@RequestBody Map<String, Object> body) {
        Long messageId = body.get("messageId") != null
                ? Long.valueOf(body.get("messageId").toString()) : null;
        String feedbackType = (String) body.get("feedbackType");
        if (messageId == null || feedbackType == null) {
            return Result.error("参数不完整");
        }
        Message msg = messageMapper.selectById(messageId);
        if (msg != null) {
            msg.setFeedbackType(feedbackType);
            msg.setFeedbackTime(LocalDateTime.now());
            messageMapper.updateById(msg);
        }
        return Result.success("ok");
    }
}

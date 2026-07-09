package com.demo.weloveShopSystem.controller.admin;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Conversation;
import com.demo.weloveShopSystem.entity.Message;
import com.demo.weloveShopSystem.mapper.ConversationMapper;
import com.demo.weloveShopSystem.mapper.MessageMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 后台对话管理控制器。
 * <p>
 * 面向运营/客服的会话审计视角,可以按用户过滤、按标题关键词搜索、查看单个对话
 * 的全部消息、看总量/今日统计,以及删除脏数据。
 */
@RestController
@RequestMapping("/api/admin/conversation")
@RequiredArgsConstructor
public class AdminConversationController {

    private final ConversationMapper conversationMapper;
    private final MessageMapper messageMapper;

    /**
     * 分页查询会话列表,返回每个会话的 user/assistant 消息数量。
     * <p>
     * 消息数量走 group by 单次查询而不是每条会话都查一次,避免 N+1。
     */
    @GetMapping("/list")
    public Result<IPage<Conversation>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) Long userId,
            @RequestParam(required = false) String keyword) {
        QueryWrapper<Conversation> qw = new QueryWrapper<>();
        if (userId != null) {
            qw.eq("user_id", userId);
        }
        if (keyword != null && !keyword.isEmpty()) {
            qw.like("title", keyword);
        }
        qw.orderByDesc("update_time");
        IPage<Conversation> result = conversationMapper.selectPage(new Page<>(page, size), qw);

        if (result.getRecords() != null && !result.getRecords().isEmpty()) {
            List<Long> convIds = result.getRecords().stream()
                    .map(Conversation::getId)
                    .collect(Collectors.toList());
            QueryWrapper<Message> mqw = new QueryWrapper<>();
            mqw.select("conversation_id", "count(*) as cnt")
                    .in("conversation_id", convIds)
                    .in("role", "user", "assistant")
                    .groupBy("conversation_id");
            Map<Long, Long> countMap = new HashMap<>();
            messageMapper.selectMaps(mqw).forEach(m -> {
                Object convId = m.get("conversation_id");
                Object cnt = m.get("cnt");
                if (convId != null && cnt != null) {
                    countMap.put(Long.valueOf(convId.toString()), ((Number) cnt).longValue());
                }
            });
            result.getRecords().forEach(c ->
                    c.setMessageCount(countMap.getOrDefault(c.getId(), 0L).intValue()));
        }
        return Result.success(result);
    }

    /** 查询指定会话的完整消息列表,按创建时间正序。 */
    @GetMapping("/{id}/messages")
    public Result<List<Message>> messages(@PathVariable Long id) {
        QueryWrapper<Message> qw = new QueryWrapper<>();
        qw.eq("conversation_id", id).orderByAsc("create_time");
        return Result.success(messageMapper.selectList(qw));
    }

    /** 会话总量、消息总量与今日新增会话数。 */
    @GetMapping("/stats")
    public Result<Map<String, Object>> stats() {
        Map<String, Object> stats = new HashMap<>();
        stats.put("totalConversations", conversationMapper.selectCount(null));
        stats.put("totalMessages", messageMapper.selectCount(null));
        stats.put("todayConversations", conversationMapper.selectCount(
                new QueryWrapper<Conversation>().ge("create_time", LocalDate.now().atStartOfDay())));
        return Result.success(stats);
    }

    /** 删除会话及其消息。 */
    @DeleteMapping("/{id}")
    public Result<Void> delete(@PathVariable Long id) {
        messageMapper.delete(new QueryWrapper<Message>().eq("conversation_id", id));
        conversationMapper.deleteById(id);
        return Result.success(null);
    }
}

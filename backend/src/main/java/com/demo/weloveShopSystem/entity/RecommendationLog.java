package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 商品推荐日志实体。
 */
@Data
@TableName(value = "recommendation_log", autoResultMap = true)
public class RecommendationLog {
    /** 推荐日志 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 用户 ID。 */
    private Long userId;
    /** 会话标识。 */
    private String sessionId;
    /** 关联消息 ID。 */
    private Long messageId;
    /** 用户查询内容。 */
    private String query;
    /** 识别出的用户意图。 */
    private String intent;
    /** 推荐商品 ID 列表。 */
    @com.baomidou.mybatisplus.annotation.TableField(typeHandler = JacksonTypeHandler.class)
    private List<Long> recommendedProductIds;
    /** 推荐理由。 */
    private String recommendReason;
    /** Agent 推理过程或理由。 */
    private String agentReasoning;
    /** 用户是否点击推荐。 */
    private Boolean userClicked;
    /** 用户反馈值。 */
    private Integer userFeedback;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

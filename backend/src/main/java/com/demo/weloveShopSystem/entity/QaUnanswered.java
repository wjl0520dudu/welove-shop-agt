package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 未回答问题统计实体。
 */
@Data
@TableName("qa_unanswered")
public class QaUnanswered {
    /** 记录 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 未回答的问题内容。 */
    private String question;
    /** 出现次数。 */
    private Integer count;
    /** 最近一次提问用户 ID。 */
    private Long lastUserId;
    /** 创建时间。 */
    private LocalDateTime createTime;
    /** 更新时间。 */
    private LocalDateTime updateTime;
}

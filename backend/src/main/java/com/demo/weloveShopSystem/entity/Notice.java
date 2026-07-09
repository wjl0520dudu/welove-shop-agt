package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 公告实体。
 */
@Data
@TableName("notice")
public class Notice {
    /** 公告 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 公告标题。 */
    private String title;
    /** 公告内容。 */
    private String content;
    /** 公告类型,例如 SYSTEM、ACTIVITY 等,由业务约定。 */
    private String noticeType;
    /** 附件或文件路径。 */
    private String filePath;
    /** 创建时间。 */
    private LocalDateTime createTime;
    /** 是否启用。 */
    private Boolean isActive;
}

package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 知识库文档实体。
 */
@Data
@TableName("knowledge_doc")
public class KnowledgeDoc {
    /** 文档 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 文档名称。 */
    private String docName;
    /** 文件存储路径或访问 URL。 */
    private String filePath;
    /** 所属分类 ID。 */
    private Long categoryId;
    /** 文档类型。 */
    private String docType;
    /** 解析状态，例如 PENDING、SUCCESS、FAILED。 */
    private String status;
    /** 解析失败时的错误信息。 */
    private String errorMessage;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

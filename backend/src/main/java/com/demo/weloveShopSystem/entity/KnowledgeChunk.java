package com.demo.weloveShopSystem.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 知识库文档切片实体。
 * <p>
 * 一个 KnowledgeDoc 会被 AI 服务切分为若干 chunk 后写入向量库,
 * 这张表主要用于回溯切片文本与文档、商品之间的关联。
 */
@Data
@TableName("knowledge_chunk")
public class KnowledgeChunk {
    /** 切片 ID。 */
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 所属文档 ID。 */
    private Long docId;
    /** 关联商品 ID,允许为空,通用类知识不必关联具体商品。 */
    private Long productId;
    /** 切片文本内容。 */
    private String chunkText;
    /** 切片序号,从 0 起,保证同一文档内切片顺序稳定。 */
    private Integer chunkIndex;
    /** 切片类型,例如 TEXT、TABLE、IMAGE_CAPTION 等,由 AI 侧约定。 */
    private String chunkType;
    /** 创建时间。 */
    private LocalDateTime createTime;
}

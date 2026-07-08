package com.demo.weloveShopSystem.dto;

import lombok.Data;

/**
 * AI 回答或中间结论引用的资料来源。
 */
@Data
public class SourceDTO {
    /** 来源标识或来源文本。 */
    private String source;
    /** 来源文档 ID。 */
    private String docId;
    /** 来源文档名称。 */
    private String docName;
    /** 来源页码，适用于 PDF 或分页文档。 */
    private Integer page;
}

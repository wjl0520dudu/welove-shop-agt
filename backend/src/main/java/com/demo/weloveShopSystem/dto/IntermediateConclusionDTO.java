package com.demo.weloveShopSystem.dto;

import lombok.Data;

import java.util.List;

/**
 * Agent 执行过程中产生的中间结论。
 */
@Data
public class IntermediateConclusionDTO {
    /** 产生该中间结论的步骤 ID。 */
    private String stepId;
    /** 结论类型，例如 intent、product_match、knowledge_summary。 */
    private String conclusionType;
    /** 结论内容，结构随结论类型变化。 */
    private Object content;
    /** 结论置信度，通常取值 0 到 1。 */
    private Double confidence;
    /** 支撑该结论的资料来源。 */
    private List<SourceDTO> sources;
}

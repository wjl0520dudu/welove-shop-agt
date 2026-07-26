package com.welove.shop.chat.dto;

import lombok.Data;
import lombok.EqualsAndHashCode;

import java.io.Serial;

/**
 * 多模态图文流式聊天请求。
 *
 * <p>与 {@link StreamChatRequest} 的唯一差异：
 * <ul>
 *   <li>新增必填 {@code imageUrl}：OSS 图片 URL(先走 /chat/upload/image 拿到)</li>
 *   <li>{@code content} 允许为空:支持"纯图搜索"(用户只上传图不打字)</li>
 * </ul>
 *
 * <p>不合并到 {@link StreamChatRequest}:让"纯文"和"图文"两条 SSE 链路端点、
 * 现在由主流式入口统一转发至 ai-service /assistant/stream，
 * 落库 message_type(text vs multimodal_image) 都明确分开,方便后续扩展视频、
 * 音频等其他多模态形式。</p>
 */
@EqualsAndHashCode(callSuper = true)
@Data
public class MultimodalStreamChatRequest extends StreamChatRequest {
    @Serial private static final long serialVersionUID = 1L;

    /**
     * OSS 图片 URL。必填。前端应先调 POST /chat/upload/image 拿到 URL 后再放这里。
     * 相对路径不接受:防止绕过 chat-service 上传 + 减少 ai-service 侧歧义。
     */
    private String imageUrl;
}

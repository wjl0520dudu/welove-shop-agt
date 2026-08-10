<template>
  <view class="row" :class="isUser ? 'user-row' : 'assistant-row'">
    <view v-if="!isUser" class="avatar ai">AI</view>
    <view class="bubble-wrap">
      <view
        class="bubble"
        :class="isUser ? 'user' : 'assistant'"
        @longpress="$emit('longpress', message)"
      >
        <TypingIndicator v-if="showTyping" />
        <template v-else>
          <!-- 用户上传的图片:多模态消息在文本上方渲染缩略图。点击预览大图。 -->
          <image
            v-if="displayImageUrl"
            class="msg-image"
            :src="displayImageUrl"
            mode="aspectFit"
            @tap="previewImage"
          />
          <MarkdownContent
            v-if="displayContent && !isUser"
            :content="displayContent"
          />
          <text
            v-else-if="displayContent"
            class="text"
            :user-select="true"
            :selectable="true"
          >{{ displayContent }}</text><text v-if="message.streaming" class="cursor">▍</text>
        </template>
      </view>
      <view v-if="message.errored" class="errored">
        <uni-icons type="info" size="13" color="#e17055" />
        <text>回复中断</text>
        <view class="retry" @tap="$emit('retry', message)">重试</view>
      </view>
      <view v-else-if="message.stopped" class="stopped-tag">
        <text class="stopped-label">已停止</text>
        <view class="retry" @tap="$emit('retry', message)">重新生成</view>
      </view>
      <view v-else-if="feedbackLabel" class="feedback-tag">
        <uni-icons :type="message.feedbackType === 'like' ? 'hand-up-filled' : 'hand-down-filled'" size="12" color="#98a2b3" />
        <text>{{ feedbackLabel }}</text>
      </view>
    </view>
    <view v-if="isUser" class="avatar user">{{ userInitial }}</view>
  </view>
</template>

<script>
import TypingIndicator from './TypingIndicator.vue'
import MarkdownContent from './MarkdownContent.vue'

export default {
  name: 'MessageBubble',
  components: { TypingIndicator, MarkdownContent },
  props: {
    message: { type: Object, required: true },
    userInitial: { type: String, default: '我' }
  },
  emits: ['longpress', 'retry'],
  computed: {
    isUser() {
      return this.message.role === 'user'
    },
    showTyping() {
      return !this.isUser && this.message.pending && !this.message.content
    },
    /**
     * 兼容 snake_case (imageUrl / image_url) 从后端来的字段。
     * 只有 user 角色 + 有图 URL 才渲染 —— assistant 不返回图片。
     */
    displayImageUrl() {
      if (!this.isUser) return ''
      return this.message.imageUrl || this.message.image_url || ''
    },
    // 纯图片消息落库时后端会写入 [图片] 占位符，图片已显示时不再重复渲染。
    displayContent() {
      const content = this.message.content || ''
      if (this.displayImageUrl && /^\[(图片|图像)\]$/.test(content.trim())) return ''
      return content
    },
    feedbackLabel() {
      if (this.message.feedbackType === 'like') return '已赞'
      if (this.message.feedbackType === 'dislike') return '已踩'
      return ''
    }
  },
  methods: {
    previewImage() {
      if (!this.displayImageUrl) return
      uni.previewImage({
        urls: [this.displayImageUrl],
        current: this.displayImageUrl
      })
    }
  }
}
</script>

<style scoped>
.row {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
  margin-bottom: 26rpx;
}
.user-row { flex-direction: row; justify-content: flex-end; }
.assistant-row { justify-content: flex-start; }
.avatar {
  flex-shrink: 0;
  width: 62rpx;
  height: 62rpx;
  border-radius: 50%;
  font-size: 24rpx;
  font-weight: 800;
  line-height: 62rpx;
  text-align: center;
}
.avatar.ai {
  background: linear-gradient(135deg, #0f766e, #14b8a6);
  color: #ffffff;
}
.avatar.user {
  background: #fff1e6;
  color: #f97316;
}
.bubble-wrap {
  max-width: 78%;
  display: flex;
  flex-direction: column;
}
.assistant-row .bubble-wrap { align-items: flex-start; }
.user-row .bubble-wrap { align-items: flex-end; }
.bubble {
  padding: 22rpx 24rpx;
  border-radius: 22rpx;
  font-size: 28rpx;
  line-height: 1.6;
  word-break: break-word;
}
.assistant {
  background: #ffffff;
  color: #344054;
  border-top-left-radius: 6rpx;
  box-shadow: 0 10rpx 26rpx rgba(15, 118, 110, 0.08);
}
.user {
  background: linear-gradient(135deg, #14b8a6, #0f9488);
  color: #ffffff;
  border-top-right-radius: 6rpx;
}
.text {
  white-space: pre-wrap;
}
/* 用户消息里的图片:占满气泡宽度、圆角、最大高度限制避免长图撑爆屏幕 */
.msg-image {
  display: block;
  width: 320rpx;
  height: 320rpx;
  max-width: 62vw;
  max-height: 480rpx;
  border-radius: 14rpx;
  margin-bottom: 12rpx;
  background: #f2f4f7;
}
.cursor {
  color: #14b8a6;
  font-weight: 700;
  animation: blink 1s step-end infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
.errored {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-top: 10rpx;
  color: #e17055;
  font-size: 22rpx;
}
.stopped-tag {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-top: 10rpx;
  color: #98a2b3;
  font-size: 22rpx;
}
.stopped-label {
  display: inline-flex;
  align-items: center;
  padding: 4rpx 12rpx;
  border-radius: 999rpx;
  background: #f2f4f7;
  color: #667085;
  font-size: 21rpx;
  font-weight: 600;
}
.retry {
  margin-left: 6rpx;
  color: #14b8a6;
  font-weight: 700;
}
.feedback-tag {
  display: flex;
  align-items: center;
  gap: 6rpx;
  margin-top: 10rpx;
  color: #98a2b3;
  font-size: 21rpx;
}
</style>

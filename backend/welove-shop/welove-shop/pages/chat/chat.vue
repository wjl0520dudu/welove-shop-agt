<template>
  <view class="page chat-shell">
    <view class="chat-header">
      <view>
        <view class="eyebrow">SHOPPING AGENT</view>
        <text class="chat-title">AI 导购</text>
        <text class="chat-subtitle">描述预算、用途和偏好，我来帮你缩小选择范围</text>
      </view>
      <view class="round-action" @tap="newChat">
        <uni-icons type="plusempty" size="22" color="#ffffff" />
      </view>
    </view>

    <scroll-view class="messages" scroll-y>
      <view class="message-row assistant-row">
        <view class="avatar">AI</view>
        <view class="message assistant">你好，我是 ShopAgent-X 导购助手。可以告诉我预算、品类、偏好或使用场景。</view>
      </view>
      <view class="quick-list">
        <view class="quick-item" @tap="fill('帮我推荐适合敏感肌的保湿面霜')">
          <uni-icons type="sparkles" size="14" color="#14b8a6" />
          <text>敏感肌面霜</text>
        </view>
        <view class="quick-item" @tap="fill('200 元以内有什么值得买的耳机')">
          <uni-icons type="sound" size="14" color="#14b8a6" />
          <text>平价耳机</text>
        </view>
        <view class="quick-item" @tap="fill('帮我对比几款热门商品')">
          <uni-icons type="bars" size="14" color="#14b8a6" />
          <text>商品对比</text>
        </view>
      </view>
    </scroll-view>

    <view class="input-bar">
      <view class="input-wrap">
        <uni-icons type="chat" size="18" color="#98a2b3" />
        <input v-model="input" class="chat-input" placeholder="输入你的购物需求" confirm-type="send" @confirm="send" />
      </view>
      <view class="send-button" @tap="send"><uni-icons type="paperplane" size="22" color="#ffffff" /></view>
    </view>
  </view>
</template>

<script>
import { requireLoginFromProtectedTab } from '../../utils/routeGuard'
export default {
  data() { return { input: '' } },
  onShow() {
    requireLoginFromProtectedTab('/pages/chat/chat')
  },
  methods: {
    fill(text) { this.input = text },
    newChat() { uni.showToast({ title: '新建会话将在第 3 周接入', icon: 'none' }) },
    send() {
      if (!this.input.trim()) {
        uni.showToast({ title: '请输入内容', icon: 'none' })
        return
      }
      uni.showToast({ title: '聊天接口将在第 3 周接入', icon: 'none' })
    }
  }
}
</script>

<style scoped>
.chat-shell {
  min-height: 100vh;
  padding-bottom: 220rpx;
  background: #f4f8f8;
}
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 24rpx;
  padding: 34rpx 30rpx;
  border-radius: 30rpx;
  background: linear-gradient(135deg, #0f766e 0%, #14b8a6 68%, #fed7aa 100%);
  color: #ffffff;
  box-shadow: 0 18rpx 42rpx rgba(20, 184, 166, 0.28);
}
.eyebrow {
  margin-bottom: 8rpx;
  font-size: 20rpx;
  letter-spacing: 1rpx;
  opacity: 0.78;
}
.chat-title {
  display: block;
  font-size: 42rpx;
  font-weight: 800;
}
.chat-subtitle {
  display: block;
  max-width: 520rpx;
  margin-top: 8rpx;
  font-size: 24rpx;
  line-height: 1.45;
  opacity: 0.9;
}
.round-action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 76rpx;
  height: 76rpx;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.22);
}
.messages {
  height: calc(100vh - 330rpx);
  padding: 0 28rpx 28rpx;
  box-sizing: border-box;
}
.message-row {
  display: flex;
  gap: 16rpx;
  align-items: flex-start;
  margin-bottom: 24rpx;
}
.avatar {
  width: 60rpx;
  height: 60rpx;
  border-radius: 50%;
  background: #fff7ed;
  color: #f97316;
  font-size: 22rpx;
  line-height: 60rpx;
  text-align: center;
  font-weight: 800;
}
.message {
  max-width: 78%;
  padding: 22rpx 24rpx;
  border-radius: 20rpx;
  font-size: 28rpx;
  line-height: 1.55;
}
.assistant {
  background: #ffffff;
  color: #344054;
  box-shadow: 0 10rpx 28rpx rgba(15, 118, 110, 0.08);
}
.quick-list {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
  padding-left: 76rpx;
}
.quick-item {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 15rpx 20rpx;
  border: 1rpx solid rgba(20, 184, 166, 0.18);
  border-radius: 999rpx;
  background: #ffffff;
  color: #344054;
  font-size: 24rpx;
  box-shadow: 0 8rpx 20rpx rgba(15, 118, 110, 0.05);
}
.input-bar {
  position: fixed;
  right: 0;
  bottom: 112rpx;
  left: 0;
  display: grid;
  grid-template-columns: 1fr 84rpx;
  gap: 16rpx;
  padding: 18rpx 24rpx calc(18rpx + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.98);
  border-top: 1rpx solid #e5e7eb;
  box-shadow: 0 -8rpx 28rpx rgba(15, 118, 110, 0.08);
  z-index: 20;
}
.input-wrap {
  display: flex;
  align-items: center;
  gap: 12rpx;
  height: 78rpx;
  padding: 0 22rpx;
  border-radius: 999rpx;
  background: #f4f8f8;
  border: 1rpx solid #dbe5e3;
}
.chat-input {
  flex: 1;
  height: 78rpx;
  font-size: 28rpx;
}
.send-button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 78rpx;
  height: 78rpx;
  border-radius: 50%;
  background: linear-gradient(135deg, #f97316, #fb923c);
  box-shadow: 0 10rpx 24rpx rgba(249, 115, 22, 0.26);
}
</style>


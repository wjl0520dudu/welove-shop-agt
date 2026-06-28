<template>
  <view class="page auth-page">
    <view class="auth-hero">
      <view class="brand-mark">
        <uni-icons type="shop" size="30" color="#ffffff" />
      </view>
      <text class="brand-name">ShopAgent-X</text>
      <text class="brand-desc">用手机号登录，继续你的智能导购体验</text>
    </view>

    <view class="form-card">
      <text class="form-title">手机号登录</text>
      <text class="form-subtitle">未注册手机号验证后将自动创建账号</text>

      <view class="field">
        <uni-icons type="phone" size="18" color="#14b8a6" />
        <input
          v-model="phone"
          class="field-input"
          type="number"
          maxlength="11"
          placeholder="请输入手机号"
        />
      </view>

      <button class="login-button" :loading="loading" :disabled="loading" @tap="handleGetCode">获取短信验证码</button>

      <view class="agreement-row">
        <uni-icons type="checkbox-filled" size="15" color="#14b8a6" />
        <text>登录即表示同意用户协议和隐私政策</text>
      </view>
    </view>
  </view>
</template>

<script>
import { sendCode } from '../../api/auth'

export default {
  data() {
    return { loading: false, phone: '', redirect: '' }
  },
  onLoad(query) {
    this.redirect = decodeURIComponent(query.redirect || '')
  },
  methods: {
    isValidPhone(phone) {
      return /^1\d{10}$/.test(phone)
    },
    async handleGetCode() {
      if (this.loading) return
      if (!this.isValidPhone(this.phone)) {
        uni.showToast({ title: '请输入正确的手机号', icon: 'none' })
        return
      }

      this.loading = true
      try {
        await sendCode(this.phone)
        uni.navigateTo({ url: `/pages/login-code/login-code?phone=${encodeURIComponent(this.phone)}&redirect=${encodeURIComponent(this.redirect)}` })
      } catch (error) {
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  padding: 34rpx 32rpx;
  box-sizing: border-box;
  background:
    radial-gradient(circle at 88% 8%, rgba(249, 115, 22, 0.18), transparent 34%),
    radial-gradient(circle at 4% 18%, rgba(20, 184, 166, 0.24), transparent 36%),
    #f4f8f8;
}
.auth-hero { padding: 64rpx 14rpx 54rpx; }
.brand-mark { display: flex; align-items: center; justify-content: center; width: 96rpx; height: 96rpx; margin-bottom: 24rpx; border-radius: 28rpx; background: linear-gradient(135deg, #0f766e, #14b8a6); box-shadow: 0 18rpx 36rpx rgba(20, 184, 166, 0.28); }
.brand-name { display: block; color: #1f2937; font-size: 52rpx; font-weight: 900; }
.brand-desc { display: block; max-width: 560rpx; margin-top: 14rpx; color: #667085; font-size: 28rpx; line-height: 1.5; }
.form-card { padding: 38rpx 30rpx 34rpx; border-radius: 30rpx; background: rgba(255, 255, 255, 0.96); box-shadow: 0 24rpx 60rpx rgba(15, 118, 110, 0.1); }
.form-title { display: block; color: #1f2937; font-size: 40rpx; font-weight: 900; }
.form-subtitle { display: block; margin: 8rpx 0 34rpx; color: #667085; font-size: 25rpx; }
.field { display: flex; align-items: center; gap: 14rpx; height: 96rpx; margin-bottom: 26rpx; padding: 0 24rpx; border: 1rpx solid #dbe5e3; border-radius: 20rpx; background: #f8fbfb; }
.field-input { flex: 1; height: 96rpx; font-size: 32rpx; font-weight: 700; color: #1f2937; }
.login-button { height: 94rpx; border-radius: 999rpx; background: linear-gradient(135deg, #14b8a6, #0f766e); color: #ffffff; font-size: 31rpx; font-weight: 900; line-height: 94rpx; box-shadow: 0 16rpx 34rpx rgba(20, 184, 166, 0.24); }
.agreement-row { display: flex; align-items: center; justify-content: center; gap: 8rpx; margin-top: 28rpx; color: #667085; font-size: 23rpx; }
</style>

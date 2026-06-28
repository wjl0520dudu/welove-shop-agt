<template>
  <view class="page auth-page">
    <view class="auth-hero compact">
      <view class="brand-mark orange">
        <uni-icons type="personadd" size="30" color="#ffffff" />
      </view>
      <text class="brand-name">创建账号</text>
      <text class="brand-desc">完善基础信息，后续可生成个性化导购推荐</text>
    </view>

    <view class="form-card">
      <view class="field"><uni-icons type="phone" size="18" color="#14b8a6" /><input v-model="form.phone" class="field-input" placeholder="手机号" /></view>
      <view class="code-row">
        <view class="field code-field"><uni-icons type="email" size="18" color="#14b8a6" /><input v-model="form.code" class="field-input" placeholder="验证码" /></view>
        <button class="code-button" @tap="handleSendCode">发送</button>
      </view>
      <view class="field"><uni-icons type="person" size="18" color="#14b8a6" /><input v-model="form.username" class="field-input" placeholder="昵称" /></view>
      <view class="field"><uni-icons type="locked" size="18" color="#14b8a6" /><input v-model="form.password" class="field-input" password placeholder="密码" /></view>
      <button class="login-button" :loading="loading" @tap="handleRegister">注册</button>
    </view>
  </view>
</template>

<script>
import { register, sendCode } from '../../api/auth'

export default {
  data() {
    return { loading: false, form: { phone: '', code: '', username: '', password: '' } }
  },
  methods: {
    async handleSendCode() {
      if (!this.form.phone) {
        uni.showToast({ title: '请输入手机号', icon: 'none' })
        return
      }
      await sendCode(this.form.phone)
      uni.showToast({ title: '验证码已发送', icon: 'none' })
    },
    async handleRegister() {
      this.loading = true
      try {
        await register(this.form)
        uni.showToast({ title: '注册成功', icon: 'success' })
        uni.navigateBack()
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
    radial-gradient(circle at 90% 8%, rgba(249, 115, 22, 0.2), transparent 34%),
    radial-gradient(circle at 6% 18%, rgba(20, 184, 166, 0.24), transparent 36%),
    #f4f8f8;
}
.auth-hero { padding: 42rpx 14rpx 34rpx; }
.brand-mark { display: flex; align-items: center; justify-content: center; width: 90rpx; height: 90rpx; margin-bottom: 22rpx; border-radius: 28rpx; background: linear-gradient(135deg, #0f766e, #14b8a6); box-shadow: 0 18rpx 36rpx rgba(20, 184, 166, 0.28); }
.brand-mark.orange { background: linear-gradient(135deg, #f97316, #fb923c); box-shadow: 0 18rpx 36rpx rgba(249, 115, 22, 0.22); }
.brand-name { display: block; color: #1f2937; font-size: 48rpx; font-weight: 900; }
.brand-desc { display: block; max-width: 560rpx; margin-top: 14rpx; color: #667085; font-size: 28rpx; line-height: 1.5; }
.form-card { padding: 34rpx 30rpx; border-radius: 30rpx; background: rgba(255, 255, 255, 0.96); box-shadow: 0 24rpx 60rpx rgba(15, 118, 110, 0.1); }
.field { display: flex; align-items: center; gap: 14rpx; height: 90rpx; margin-bottom: 22rpx; padding: 0 24rpx; border: 1rpx solid #dbe5e3; border-radius: 18rpx; background: #f8fbfb; box-sizing: border-box; }
.field-input { flex: 1; height: 90rpx; font-size: 28rpx; }
.code-row { display: grid; grid-template-columns: 1fr 152rpx; gap: 16rpx; }
.code-field { min-width: 0; }
.code-button { height: 90rpx; padding: 0; border-radius: 18rpx; background: #fff7ed; color: #f97316; font-size: 27rpx; font-weight: 800; line-height: 90rpx; }
.login-button { height: 92rpx; margin-top: 8rpx; border-radius: 999rpx; background: linear-gradient(135deg, #14b8a6, #0f766e); color: #ffffff; font-size: 31rpx; font-weight: 800; line-height: 92rpx; box-shadow: 0 16rpx 34rpx rgba(20, 184, 166, 0.24); }
</style>

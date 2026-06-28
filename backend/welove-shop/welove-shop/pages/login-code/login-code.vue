<template>
  <view class="page code-page">
    <view class="code-header">
      <view class="back" @tap="goBack">
        <uni-icons type="left" size="22" color="#1f2937" />
      </view>
      <text class="code-title">输入验证码</text>
      <text class="code-desc">验证码已发送至 {{ maskedPhone }}</text>
    </view>

    <view class="code-card">
      <view class="code-boxes" @tap="focusInput">
        <view v-for="index in 6" :key="index" class="code-cell" :class="{ active: code.length === index - 1 }">
          <text>{{ code[index - 1] || '' }}</text>
        </view>
        <input
          class="hidden-input"
          v-model="code"
          type="number"
          maxlength="6"
          :focus="inputFocused"
          @input="onCodeInput"
          @paste="onCodePaste"
        />
      </view>

      <button
        class="login-button"
        :loading="loading"
        :disabled="loading || code.length !== 6"
        :class="{ disabled: loading || code.length !== 6 }"
        @tap="verifyCode"
      >登录</button>

      <view class="resend-row">
        <text v-if="seconds > 0">{{ seconds }} 秒后可重新发送</text>
        <text v-else class="resend" @tap="resendCode">重新发送验证码</text>
      </view>
    </view>
  </view>
</template>

<script>
import { sendCode } from '../../api/auth'
import userStore from '../../store/user'

export default {
  data() {
    return { phone: '', code: '', seconds: 60, timer: null, loading: false, resending: false, inputFocused: true, redirect: '' }
  },
  computed: {
    maskedPhone() {
      if (!this.phone || this.phone.length < 11) return this.phone
      return `${this.phone.slice(0, 3)}****${this.phone.slice(7)}`
    }
  },
  onLoad(query) {
    this.phone = decodeURIComponent(query.phone || '')
    this.redirect = decodeURIComponent(query.redirect || '')
    this.startTimer()
  },
  onUnload() {
    if (this.timer) clearInterval(this.timer)
  },
  methods: {
    focusInput() {
      this.inputFocused = false
      this.$nextTick(() => {
        this.inputFocused = true
      })
    },
    goBack() { uni.navigateBack() },
    normalizeCode(value) {
      return String(value || '').replace(/\D/g, '').slice(0, 6)
    },
    onCodeInput(event) {
      this.code = this.normalizeCode(event.detail.value)
    },
    onCodePaste(event) {
      const value = event?.detail?.value || event?.clipboardData?.getData?.('text') || ''
      const code = this.normalizeCode(value)
      if (code) this.code = code
    },
    startTimer() {
      if (this.timer) clearInterval(this.timer)
      this.seconds = 60
      this.timer = setInterval(() => {
        if (this.seconds <= 1) {
          clearInterval(this.timer)
          this.timer = null
          this.seconds = 0
        } else {
          this.seconds -= 1
        }
      }, 1000)
    },
    async resendCode() {
      if (this.resending || this.seconds > 0) return
      this.resending = true
      try {
        await sendCode(this.phone)
        this.code = ''
        this.startTimer()
        uni.showToast({ title: '验证码已发送', icon: 'none' })
      } catch (error) {
      } finally {
        this.resending = false
      }
    },
    goAfterLogin() {
      const target = this.redirect || '/pages/product-list/product-list'
      const tabPages = ['/pages/chat/chat', '/pages/product-list/product-list', '/pages/cart/cart', '/pages/profile/profile']
      const targetPath = target.split('?')[0]
      if (tabPages.includes(targetPath)) {
        uni.switchTab({ url: targetPath })
      } else {
        uni.redirectTo({ url: target })
      }
    },
    async verifyCode() {
      if (this.loading || this.code.length !== 6) return
      this.loading = true
      try {
        await userStore.login({ phone: this.phone, code: this.code })
        this.goAfterLogin()
      } catch (error) {
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.code-page { min-height: 100vh; padding: 32rpx; box-sizing: border-box; background: radial-gradient(circle at 88% 8%, rgba(249, 115, 22, 0.16), transparent 34%), radial-gradient(circle at 4% 18%, rgba(20, 184, 166, 0.22), transparent 36%), #f4f8f8; }
.code-header { padding: 18rpx 4rpx 54rpx; }
.back { display: flex; align-items: center; justify-content: center; width: 72rpx; height: 72rpx; margin-bottom: 38rpx; border-radius: 50%; background: rgba(255,255,255,0.86); box-shadow: 0 10rpx 28rpx rgba(15, 118, 110, 0.08); }
.code-title { display: block; color: #1f2937; font-size: 48rpx; font-weight: 900; }
.code-desc { display: block; margin-top: 14rpx; color: #667085; font-size: 28rpx; }
.code-card { padding: 38rpx 28rpx 34rpx; border-radius: 30rpx; background: rgba(255,255,255,0.96); box-shadow: 0 24rpx 60rpx rgba(15, 118, 110, 0.1); }
.code-boxes { position: relative; display: grid; grid-template-columns: repeat(6, 1fr); gap: 14rpx; margin-bottom: 34rpx; }
.code-cell { height: 86rpx; border-radius: 18rpx; background: #f8fbfb; border: 2rpx solid #dbe5e3; text-align: center; line-height: 86rpx; color: #1f2937; font-size: 36rpx; font-weight: 900; }
.code-cell.active { border-color: #14b8a6; background: #f0fdfa; }
.hidden-input { position: absolute; left: 0; right: 0; top: 0; width: 100%; height: 86rpx; opacity: 0; z-index: 2; }
.login-button { height: 94rpx; border-radius: 999rpx; background: linear-gradient(135deg, #14b8a6, #0f766e); color: #ffffff; font-size: 31rpx; font-weight: 900; line-height: 94rpx; box-shadow: 0 16rpx 34rpx rgba(20, 184, 166, 0.24); }
.login-button.disabled { opacity: 0.45; box-shadow: none; }
.resend-row { margin-top: 28rpx; text-align: center; color: #667085; font-size: 26rpx; }
.resend { color: #f97316; font-weight: 800; }
</style>
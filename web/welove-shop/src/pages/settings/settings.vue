<template>
  <view class="page settings-page">
    <view class="group-card">
      <text class="group-label">账号与安全</text>
      <view class="menu-item" @tap="go('/pages/profile-edit/profile-edit')">
        <view class="menu-icon"><uni-icons type="person" size="18" color="#14b8a6" /></view>
        <text class="menu-text">编辑资料</text>
        <uni-icons type="right" size="16" color="#98a2b3" />
      </view>
      <!-- 修改密码：骨架期手机号登录无密码，暂时隐藏 -->
      <!--
      <view class="menu-item" @tap="go('/pages/change-password/change-password')">
        <view class="menu-icon"><uni-icons type="locked" size="18" color="#14b8a6" /></view>
        <text class="menu-text">修改密码</text>
        <uni-icons type="right" size="16" color="#98a2b3" />
      </view>
      -->
    </view>

    <view class="group-card">
      <text class="group-label">通用</text>
      <view class="menu-item" @tap="goPage('/pages/about/about')">
        <view class="menu-icon"><uni-icons type="info" size="18" color="#14b8a6" /></view>
        <text class="menu-text">关于我们</text>
        <uni-icons type="right" size="16" color="#98a2b3" />
      </view>
    </view>

    <button v-if="loggedIn" class="logout-btn" @tap="logout">退出登录</button>
    <button v-else class="login-btn" @tap="goLogin">登录账号</button>
  </view>
</template>

<script>
import userStore from '../../store/user'
import cartStore from '../../store/cart'
import { requireLogin, toLogin } from '../../utils/routeGuard'

export default {
  data() {
    return { loggedIn: userStore.isLoggedIn() }
  },
  onShow() {
    userStore.restore()
    this.loggedIn = userStore.isLoggedIn()
  },
  methods: {
    go(url) {
      if (!requireLogin(url)) return
      uni.navigateTo({ url })
    },
    goPage(url) {
      uni.navigateTo({ url })
    },
    goLogin() {
      toLogin('/pages/settings/settings')
    },
    logout() {
      if (!this.loggedIn) return
      uni.showModal({
        title: '退出登录',
        content: '确定要退出当前账号吗？',
        success: (res) => {
          if (!res.confirm) return
          userStore.logout()
          this.loggedIn = false
          uni.switchTab({
            url: '/pages/profile/profile',
            complete: () => {
              // 切回 TabBar 后再执行一次，覆盖部分 H5 运行时的延迟挂载。
              cartStore.flushBadge()
            }
          })
        }
      })
    }
  }
}
</script>

<style scoped>
.settings-page {
  min-height: 100vh;
  padding: 24rpx 24rpx calc(40rpx + env(safe-area-inset-bottom));
  box-sizing: border-box;
  background: #f4f8f8;
}
.group-card {
  margin-bottom: 22rpx;
  padding: 20rpx 0 4rpx;
  border-radius: 24rpx;
  background: #ffffff;
  box-shadow: 0 12rpx 34rpx rgba(15, 118, 110, 0.07);
}
.group-label {
  display: block;
  padding: 0 26rpx 8rpx;
  color: #98a2b3;
  font-size: 24rpx;
  font-weight: 800;
}
.menu-item {
  display: flex;
  align-items: center;
  min-height: 100rpx;
  padding: 0 26rpx;
  border-top: 1rpx solid #f2f4f7;
}
.menu-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 54rpx;
  height: 54rpx;
  margin-right: 18rpx;
  border-radius: 16rpx;
  background: #f0fdfa;
}
.menu-text {
  flex: 1;
  color: #1f2937;
  font-size: 29rpx;
  font-weight: 600;
}
.logout-btn {
  height: 92rpx;
  margin-top: 20rpx;
  border-radius: 999rpx;
  background: #ffffff;
  color: #e17055;
  font-size: 30rpx;
  font-weight: 800;
  line-height: 92rpx;
  box-shadow: 0 12rpx 30rpx rgba(15, 118, 110, 0.06);
}
.login-btn {
  height: 92rpx;
  margin-top: 20rpx;
  border-radius: 999rpx;
  background: linear-gradient(135deg, #0f766e, #14b8a6);
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 800;
  line-height: 92rpx;
}
</style>

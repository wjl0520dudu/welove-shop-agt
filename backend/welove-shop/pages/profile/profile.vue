<template>
  <view class="page profile-page">
    <view class="profile-hero">
      <view class="avatar">{{ avatarText }}</view>
      <view class="profile-main">
        <text class="profile-name">{{ user && user.username ? user.username : '未登录用户' }}</text>
        <text class="profile-phone">{{ user && user.phone ? user.phone : '登录后同步订单、地址和偏好' }}</text>
      </view>
      <button v-if="!loggedIn" class="login-button" @tap="goLogin">登录</button>
    </view>

    <view class="stat-row">
      <view class="stat-item" @tap="go('/pages/favorite/favorite')"><text class="stat-num">0</text><text class="stat-label">收藏</text></view>
      <view class="stat-item" @tap="go('/pages/browse-history/browse-history')"><text class="stat-num">0</text><text class="stat-label">浏览</text></view>
      <view class="stat-item" @tap="go('/pages/order-list/order-list')"><text class="stat-num">0</text><text class="stat-label">订单</text></view>
    </view>

    <view class="menu-card">
      <view class="menu-item" v-for="item in menus" :key="item.text" @tap="go(item.url)">
        <view class="menu-icon"><uni-icons :type="item.icon" size="19" color="#14b8a6" /></view>
        <text class="menu-text">{{ item.text }}</text>
        <uni-icons type="right" size="17" color="#98a2b3" />
      </view>
    </view>
  </view>
</template>

<script>
import userStore from '../../store/user'
import { requireLogin } from '../../utils/routeGuard'

export default {
  data() {
    return {
      user: userStore.state.user,
      loggedIn: userStore.isLoggedIn(),
      menus: [
        { text: '我的订单', icon: 'list', url: '/pages/order-list/order-list' },
        { text: '地址管理', icon: 'location', url: '/pages/address-list/address-list' },
        { text: '我的收藏', icon: 'star', url: '/pages/favorite/favorite' },
        { text: '浏览历史', icon: 'calendar', url: '/pages/browse-history/browse-history' },
        { text: '设置', icon: 'gear', url: '/pages/settings/settings' }
      ]
    }
  },
  computed: {
    avatarText() {
      const name = this.user && this.user.username ? this.user.username : '我'
      return name.slice(0, 1)
    }
  },
  onShow() {
    userStore.restore()
    this.user = userStore.state.user
    this.loggedIn = userStore.isLoggedIn()
  },
  methods: {
    goLogin() { uni.navigateTo({ url: '/pages/login/login' }) },
    go(url) {
      if (!requireLogin(url)) return
      uni.navigateTo({ url })
    }
  }
}
</script>

<style scoped>
.profile-page { padding: 24rpx 24rpx 140rpx; }
.profile-hero { display: flex; align-items: center; gap: 20rpx; padding: 36rpx 30rpx; border-radius: 30rpx; background: linear-gradient(135deg, #0f766e, #14b8a6 70%, #fed7aa); color: #ffffff; box-shadow: 0 18rpx 42rpx rgba(20, 184, 166, 0.25); }
.avatar { width: 98rpx; height: 98rpx; border-radius: 50%; background: rgba(255,255,255,0.22); color: #ffffff; text-align: center; line-height: 98rpx; font-size: 42rpx; font-weight: 800; }
.profile-main { flex: 1; min-width: 0; }
.profile-name { display: block; font-size: 34rpx; font-weight: 800; }
.profile-phone { display: block; margin-top: 8rpx; font-size: 24rpx; opacity: 0.86; }
.login-button { width: 132rpx; height: 64rpx; padding: 0; border-radius: 999rpx; background: #fff7ed; color: #f97316; font-size: 26rpx; font-weight: 700; line-height: 64rpx; }
.stat-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16rpx; margin: 22rpx 0; }
.stat-item { padding: 24rpx 0; border-radius: 20rpx; background: #ffffff; text-align: center; box-shadow: 0 10rpx 28rpx rgba(15, 118, 110, 0.06); }
.stat-num { display: block; color: #f97316; font-size: 34rpx; font-weight: 800; }
.stat-label { display: block; margin-top: 4rpx; color: #667085; font-size: 24rpx; }
.menu-card { overflow: hidden; border-radius: 24rpx; background: #ffffff; box-shadow: 0 12rpx 34rpx rgba(15, 118, 110, 0.07); }
.menu-item { display: flex; align-items: center; min-height: 100rpx; padding: 0 26rpx; border-bottom: 1rpx solid #eef2f6; }
.menu-icon { display: flex; align-items: center; justify-content: center; width: 54rpx; height: 54rpx; margin-right: 18rpx; border-radius: 16rpx; background: #f0fdfa; }
.menu-text { flex: 1; color: #1f2937; font-size: 30rpx; font-weight: 600; }
</style>

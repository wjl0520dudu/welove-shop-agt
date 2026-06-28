<template>
  <view class="page profile-page">
    <view v-if="loggedIn" class="profile-hero" @tap="go('/pages/profile-edit/profile-edit')">
      <view class="avatar">{{ avatarText }}</view>
      <view class="profile-main">
        <text class="profile-name">{{ userName }}</text>
        <text class="profile-phone">{{ userPhone }}</text>
      </view>
      <uni-icons type="right" size="18" color="#ffffff" />
    </view>

    <view v-else class="profile-hero guest">
      <view class="avatar">我</view>
      <view class="profile-main">
        <text class="profile-name">未登录用户</text>
        <text class="profile-phone">登录后同步订单、地址和偏好</text>
      </view>
      <button class="login-button" @tap="goLogin">登录</button>
    </view>

    <view class="stat-row">
      <view class="stat-item" @tap="go('/pages/favorite/favorite')"><text class="stat-num">{{ stats.favorite }}</text><text class="stat-label">收藏</text></view>
      <view class="stat-item" @tap="go('/pages/browse-history/browse-history')"><text class="stat-num">{{ stats.history }}</text><text class="stat-label">浏览</text></view>
      <view class="stat-item" @tap="go('/pages/order-list/order-list')"><text class="stat-num">{{ stats.order }}</text><text class="stat-label">订单</text></view>
    </view>

    <view v-if="loggedIn && hasProfileInfo" class="profile-card">
      <text class="card-title">个人资料</text>
      <view class="tag-row">
        <text v-if="genderText" class="tag">{{ genderText }}</text>
        <text v-if="user && user.ageRange" class="tag">{{ user.ageRange }}</text>
        <text v-if="user && user.skinType" class="tag">{{ user.skinType }}</text>
        <text v-for="tag in preferenceTags" :key="tag" class="tag muted">{{ tag }}</text>
      </view>
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
import { getOrderList } from '../../api/order'
import { getFavoriteList, getBrowseHistory } from '../../api/recommend'
import { requireLogin } from '../../utils/routeGuard'

export default {
  data() {
    return {
      user: userStore.state.user,
      loggedIn: userStore.isLoggedIn(),
      stats: { favorite: 0, history: 0, order: 0 },
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
    userName() { return this.user?.username || '未设置昵称' },
    userPhone() { return this.user?.phone || '' },
    avatarText() { return (this.userName || '我').slice(0, 1) },
    preferenceTags() { return Array.isArray(this.user?.preferenceTags) ? this.user.preferenceTags : [] },
    genderText() { const map = { 1: '男', 2: '女' }; return map[this.user?.gender] || '' },
    hasProfileInfo() { return Boolean(this.genderText || this.user?.ageRange || this.user?.skinType || this.preferenceTags.length) }
  },
  onShow() {
    this.refreshLocalUser()
    if (this.loggedIn) {
      this.loadProfile()
      this.loadStats()
    } else {
      this.stats = { favorite: 0, history: 0, order: 0 }
    }
  },
  methods: {
    refreshLocalUser() { userStore.restore(); this.user = userStore.state.user; this.loggedIn = userStore.isLoggedIn() },
    async loadProfile() { try { await userStore.loadProfile(); this.refreshLocalUser() } catch (error) { this.refreshLocalUser() } },
    async loadStats() {
      const [orders, favorites, histories] = await Promise.allSettled([
        getOrderList({ page: 1, size: 1 }), getFavoriteList(), getBrowseHistory()
      ])
      if (orders.status === 'fulfilled') this.stats.order = Number(orders.value?.total || orders.value?.records?.length || 0)
      if (favorites.status === 'fulfilled') this.stats.favorite = Array.isArray(favorites.value) ? favorites.value.length : 0
      if (histories.status === 'fulfilled') this.stats.history = Array.isArray(histories.value) ? histories.value.length : 0
    },
    goLogin() { uni.navigateTo({ url: '/pages/login/login' }) },
    go(url) { if (!requireLogin(url)) return; uni.navigateTo({ url }) }
  }
}
</script>

<style scoped>
.profile-page{padding:24rpx 24rpx 140rpx}.profile-hero{display:flex;align-items:center;gap:20rpx;padding:36rpx 30rpx;border-radius:30rpx;background:linear-gradient(135deg,#0f766e,#14b8a6 70%,#fed7aa);color:#fff;box-shadow:0 18rpx 42rpx rgba(20,184,166,.25)}.profile-hero.guest{background:linear-gradient(135deg,#344054,#14b8a6)}.avatar{width:98rpx;height:98rpx;border-radius:50%;background:rgba(255,255,255,.22);color:#fff;text-align:center;line-height:98rpx;font-size:42rpx;font-weight:800}.profile-main{flex:1;min-width:0}.profile-name{display:block;font-size:34rpx;font-weight:800}.profile-phone{display:block;margin-top:8rpx;font-size:24rpx;opacity:.86}.login-button{width:132rpx;height:64rpx;padding:0;border-radius:999rpx;background:#fff7ed;color:#f97316;font-size:26rpx;font-weight:700;line-height:64rpx}.stat-row{display:grid;grid-template-columns:repeat(3,1fr);gap:16rpx;margin:22rpx 0}.stat-item{padding:24rpx 0;border-radius:20rpx;background:#fff;text-align:center;box-shadow:0 10rpx 28rpx rgba(15,118,110,.06)}.stat-num{display:block;color:#f97316;font-size:34rpx;font-weight:800}.stat-label{display:block;margin-top:4rpx;color:#667085;font-size:24rpx}.profile-card,.menu-card{border-radius:24rpx;background:#fff;box-shadow:0 12rpx 34rpx rgba(15,118,110,.07)}.profile-card{margin-bottom:22rpx;padding:24rpx}.card-title{display:block;margin-bottom:16rpx;color:#1f2937;font-size:28rpx;font-weight:900}.tag-row{display:flex;flex-wrap:wrap;gap:12rpx}.tag{padding:8rpx 14rpx;border-radius:999rpx;background:#ecfdf9;color:#0f766e;font-size:23rpx;font-weight:800}.tag.muted{background:#f2f4f7;color:#667085}.menu-card{overflow:hidden}.menu-item{display:flex;align-items:center;min-height:100rpx;padding:0 26rpx;border-bottom:1rpx solid #eef2f6}.menu-icon{display:flex;align-items:center;justify-content:center;width:54rpx;height:54rpx;margin-right:18rpx;border-radius:16rpx;background:#f0fdfa}.menu-text{flex:1;color:#1f2937;font-size:30rpx;font-weight:600}
</style>

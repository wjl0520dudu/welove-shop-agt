<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">设置</text>
        <text class="subtitle">管理账号状态、修改密码和项目相关信息。</text>
      </view>

      <button v-if="loggedIn" class="secondary-button" @tap="logout">退出登录</button>
      <button v-else class="primary-button" @tap="goLogin">登录账号</button>
    </view>
  </view>
</template>

<script>
import userStore from '../../store/user'
import cartStore from '../../store/cart'
import { toLogin } from '../../utils/routeGuard'

export default {
  data() {
    return { loggedIn: userStore.isLoggedIn() }
  },
  onShow() {
    userStore.restore()
    this.loggedIn = userStore.isLoggedIn()
  },
  methods: {
    goLogin() {
      toLogin('/pages/settings/settings')
    },
    logout() {
      if (!this.loggedIn) return
      userStore.logout()
      cartStore.reset()
      this.loggedIn = false
      uni.switchTab({ url: '/pages/profile/profile' })
    }
  }
}
</script>
<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">修改密码</text>
        <text class="subtitle">登录后可修改账号密码。</text>
      </view>
    </view>
  </view>
</template>

<script>
import { requireLogin } from '../../utils/routeGuard'

export default {
  onLoad() {
    requireLogin('/pages/change-password/change-password')
  }
}
</script>
<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">编辑资料</text>
        <text class="subtitle">登录后可编辑昵称、头像和偏好信息。</text>
      </view>
    </view>
  </view>
</template>

<script>
import { requireLogin } from '../../utils/routeGuard'

export default {
  onLoad() {
    requireLogin('/pages/profile-edit/profile-edit')
  }
}
</script>
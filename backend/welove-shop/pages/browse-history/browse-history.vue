<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">浏览历史</text>
        <text class="subtitle">登录后可查看你的商品浏览记录。</text>
      </view>
    </view>
  </view>
</template>

<script>
import { requireLogin } from '../../utils/routeGuard'

export default {
  onLoad() {
    requireLogin('/pages/browse-history/browse-history')
  }
}
</script>
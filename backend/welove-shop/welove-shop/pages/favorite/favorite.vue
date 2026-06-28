<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">我的收藏</text>
        <text class="subtitle">登录后可查看你收藏的商品。</text>
      </view>
    </view>
  </view>
</template>

<script>
import { requireLogin } from '../../utils/routeGuard'

export default {
  onLoad() {
    requireLogin('/pages/favorite/favorite')
  }
}
</script>
<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">我的订单</text>
        <text class="subtitle">登录后可查看订单列表和订单状态。</text>
      </view>
    </view>
  </view>
</template>

<script>
import { requireLogin } from '../../utils/routeGuard'

export default {
  onLoad() {
    requireLogin('/pages/order-list/order-list')
  }
}
</script>
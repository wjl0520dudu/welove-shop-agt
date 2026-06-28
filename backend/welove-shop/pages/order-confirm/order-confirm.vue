<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">确认订单</text>
        <text class="subtitle">第 2 周接入地址、购物车选中商品和创建订单接口。</text>
      </view>
      <button class="primary-button" @tap="submit">提交订单</button>
    </view>
  </view>
</template>

<script>
import { requireLogin } from '../../utils/routeGuard'

export default {
  onLoad() {
    if (!requireLogin('/pages/order-confirm/order-confirm')) return
  },
  methods: {
    submit() { uni.showToast({ title: '订单创建将在第 2 周接入', icon: 'none' }) }
  }
}
</script>

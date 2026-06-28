<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">地址管理</text>
        <text class="subtitle">第 2 周接入地址列表、新增、编辑、默认地址。</text>
      </view>
      <button class="primary-button" @tap="goEdit">新增地址</button>
    </view>
  </view>
</template>

<script>
import { requireLogin } from '../../utils/routeGuard'

export default {
  onLoad() {
    if (!requireLogin('/pages/address-list/address-list')) return
  },
  methods: {
    goEdit() { uni.navigateTo({ url: '/pages/address-edit/address-edit' }) }
  }
}
</script>

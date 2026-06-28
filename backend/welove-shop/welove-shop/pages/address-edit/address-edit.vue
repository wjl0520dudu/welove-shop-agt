<template>
  <view class="page">
    <view class="page-body">
      <view class="section">
        <text class="title">编辑地址</text>
        <text class="subtitle">登录后可新增或编辑收货地址。</text>
      </view>
    </view>
  </view>
</template>

<script>
import { requireLogin } from '../../utils/routeGuard'

export default {
  onLoad() {
    requireLogin('/pages/address-edit/address-edit')
  }
}
</script>
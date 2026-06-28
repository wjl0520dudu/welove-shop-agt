<template>
  <view class="page checkout-page">
    <view class="address-card" @tap="chooseAddress">
      <view v-if="address" class="address-main"><view class="address-head"><text class="receiver">{{ address.receiverName }}</text><text class="phone">{{ address.phone }}</text><text v-if="isDefault(address)" class="default-tag">默认</text></view><text class="address-text">{{ fullAddress(address) }}</text></view>
      <view v-else class="address-empty"><uni-icons type="location" size="22" color="#14b8a6" /><text>请选择收货地址</text></view>
      <uni-icons type="right" size="16" color="#98a2b3" />
    </view>
    <view class="section muted-section"><text class="title">确认订单</text><text class="subtitle">订单商品和创建订单接口将在 Day10 接入。</text></view>
    <button class="primary-button" @tap="submit">提交订单</button>
  </view>
</template>
<script>
import { getAddressList } from '../../api/address'
import { requireLogin } from '../../utils/routeGuard'
export default { data() { return { address: null, loadingAddress: false } }, onLoad() { if (!requireLogin('/pages/order-confirm/order-confirm')) return }, onShow() { if (!requireLogin('/pages/order-confirm/order-confirm')) return; const selected = uni.getStorageSync('selectedAddress'); if (selected && selected.id) { this.address = selected; uni.removeStorageSync('selectedAddress'); return } if (!this.address) this.loadDefaultAddress() }, methods: { async loadDefaultAddress() { this.loadingAddress = true; try { const list = await getAddressList(); const addresses = Array.isArray(list) ? list : []; this.address = addresses.find(item => this.isDefault(item)) || addresses[0] || null } catch (error) { uni.showToast({ title: '地址加载失败', icon: 'none' }) } finally { this.loadingAddress = false } }, isDefault(item) { return item?.isDefault === 1 || item?.isDefault === true }, fullAddress(item) { return `${item.province || ''}${item.city || ''}${item.district || ''}${item.detail || ''}` }, chooseAddress() { uni.navigateTo({ url: '/pages/address-list/address-list?select=1' }) }, submit() { if (!this.address) { uni.showToast({ title: '请选择收货地址', icon: 'none' }); return } uni.showToast({ title: '订单创建将在 Day10 接入', icon: 'none' }) } } }
</script>
<style scoped>
.checkout-page{min-height:100vh;padding:22rpx}.address-card{display:flex;align-items:center;gap:18rpx;margin-bottom:20rpx;padding:26rpx;border-radius:24rpx;background:#fff;box-shadow:0 10rpx 28rpx rgba(15,118,110,.06)}.address-main{flex:1;min-width:0}.address-head{display:flex;align-items:center;gap:14rpx}.receiver{color:#1f2937;font-size:31rpx;font-weight:900}.phone{color:#667085;font-size:27rpx;font-weight:700}.default-tag{padding:4rpx 10rpx;border-radius:8rpx;background:#ccfbf1;color:#0f766e;font-size:22rpx;font-weight:800}.address-text{display:block;margin-top:14rpx;color:#344054;font-size:28rpx;line-height:1.45}.address-empty{display:flex;align-items:center;gap:12rpx;flex:1;color:#1f2937;font-size:30rpx;font-weight:800}.muted-section{background:#fff}
</style>

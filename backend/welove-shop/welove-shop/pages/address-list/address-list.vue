<template>
  <view class="page address-page">
    <view v-if="loading" class="loading-wrap"><uni-load-more status="loading" :contentText="loadText" /></view>
    <view v-else-if="errorMessage" class="state-wrap">
      <EmptyState title="地址加载失败" :description="errorMessage" />
      <button class="retry" @tap="loadAddresses">重新加载</button>
    </view>
    <view v-else-if="!addresses.length" class="empty-wrap">
      <EmptyState title="暂无收货地址" description="添加常用收货地址，结算时会更方便。" />
      <button class="primary-button add-empty" @tap="goEdit">添加地址</button>
    </view>
    <scroll-view v-else scroll-y class="address-scroll">
      <view v-for="item in addresses" :key="item.id" class="address-card" :class="{ default: isDefault(item), selectable: selectMode }" @tap="selectAddress(item)">
        <view class="card-head">
          <text class="receiver">{{ item.receiverName }}</text><text class="phone">{{ item.phone }}</text><text v-if="isDefault(item)" class="default-tag">默认</text>
        </view>
        <text class="address-text">{{ fullAddress(item) }}</text>
        <view class="card-actions" @tap.stop>
          <button v-if="!isDefault(item)" class="plain-btn" @tap="setDefault(item)">设为默认</button>
          <button class="icon-btn" @tap="goEdit(item)"><uni-icons type="compose" size="18" color="#667085" /></button>
          <button class="icon-btn" @tap="confirmDelete(item)"><uni-icons type="trash" size="18" color="#ef4444" /></button>
        </view>
      </view>
      <view class="bottom-spacer"></view>
    </scroll-view>
    <button class="fab-add" @tap="goEdit"><uni-icons type="plusempty" size="18" color="#ffffff" /><text>新增地址</text></button>
  </view>
</template>

<script>
import EmptyState from '../../components/EmptyState.vue'
import { deleteAddress, getAddressList, setDefaultAddress } from '../../api/address'
import { requireLogin } from '../../utils/routeGuard'
export default {
  components: { EmptyState },
  data() { return { addresses: [], loading: false, errorMessage: '', selectMode: false, loadText: { contentdown: '加载更多', contentrefresh: '正在加载...', contentnomore: '没有更多了' } } },
  onLoad(options = {}) { if (!requireLogin('/pages/address-list/address-list')) return; this.selectMode = options.select === '1' },
  onShow() { if (!requireLogin('/pages/address-list/address-list')) return; this.loadAddresses() },
  onPullDownRefresh() { this.loadAddresses().finally(() => uni.stopPullDownRefresh()) },
  methods: {
    async loadAddresses() { this.loading = true; try { const data = await getAddressList(); this.addresses = Array.isArray(data) ? data : []; this.errorMessage = '' } catch (error) { this.errorMessage = error.message || '请稍后重试' } finally { this.loading = false } },
    isDefault(item) { return item.isDefault === 1 || item.isDefault === true },
    fullAddress(item) { return `${item.province || ''}${item.city || ''}${item.district || ''}${item.detail || ''}` },
    goEdit(item) { const query = item?.id ? `?id=${item.id}` : ''; uni.navigateTo({ url: `/pages/address-edit/address-edit${query}` }) },
    selectAddress(item) { if (!this.selectMode) return; uni.setStorageSync('selectedAddress', item); uni.navigateBack() },
    async setDefault(item) { try { await setDefaultAddress(item.id); this.addresses = this.addresses.map(address => ({ ...address, isDefault: address.id === item.id ? 1 : 0 })); uni.showToast({ title: '已设为默认', icon: 'none' }) } catch (error) { uni.showToast({ title: '设置失败', icon: 'none' }) } },
    confirmDelete(item) { uni.showModal({ title: '删除地址', content: '确定删除这条收货地址吗？', confirmColor: '#ef4444', success: async (res) => { if (res.confirm) await this.removeAddress(item) } }) },
    async removeAddress(item) { try { await deleteAddress(item.id); this.addresses = this.addresses.filter(address => address.id !== item.id); uni.showToast({ title: '已删除', icon: 'none' }) } catch (error) { uni.showToast({ title: '删除失败', icon: 'none' }) } }
  }
}
</script>

<style scoped>
.address-page{min-height:100vh;padding:20rpx 22rpx 130rpx}.loading-wrap,.state-wrap,.empty-wrap{padding:96rpx 0}.retry,.add-empty{width:240rpx;height:76rpx;margin:18rpx auto 0;border-radius:999rpx;background:#14b8a6;color:#fff;font-size:28rpx;line-height:76rpx}.address-scroll{height:calc(100vh - 150rpx)}.address-card{margin-bottom:18rpx;padding:26rpx;border:2rpx solid transparent;border-radius:24rpx;background:#fff;box-shadow:0 10rpx 28rpx rgba(15,118,110,.06)}.address-card.default{border-color:#14b8a6}.address-card.selectable:active{background:#ecfdf9}.card-head{display:flex;align-items:center;gap:14rpx;min-width:0}.receiver{color:#1f2937;font-size:31rpx;font-weight:900}.phone{color:#667085;font-size:27rpx;font-weight:700}.default-tag{padding:4rpx 10rpx;border-radius:8rpx;background:#ccfbf1;color:#0f766e;font-size:22rpx;font-weight:800}.address-text{display:block;margin-top:14rpx;color:#344054;font-size:28rpx;line-height:1.45}.card-actions{display:flex;align-items:center;justify-content:flex-end;gap:14rpx;margin-top:18rpx}.plain-btn,.icon-btn{margin:0;padding:0;background:transparent;line-height:1}.plain-btn{color:#14b8a6;font-size:25rpx;font-weight:800}.icon-btn{display:flex;align-items:center;justify-content:center;width:58rpx;height:58rpx;border-radius:50%;background:#f2f4f7}.fab-add{position:fixed;right:28rpx;bottom:calc(28rpx + env(safe-area-inset-bottom));display:flex;align-items:center;justify-content:center;gap:8rpx;width:230rpx;height:78rpx;border-radius:999rpx;background:#14b8a6;color:#fff;font-size:28rpx;font-weight:900;line-height:78rpx;box-shadow:0 12rpx 28rpx rgba(20,184,166,.24)}.bottom-spacer{height:120rpx}
</style>

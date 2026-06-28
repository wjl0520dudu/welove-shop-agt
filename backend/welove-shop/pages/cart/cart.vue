<template>
  <view class="page cart-page">
    <view class="cart-top">
      <view class="top-main">
        <text class="cart-title-main">购物车</text>
        <text class="cart-count">({{ items.length }})</text>
      </view>
      <view class="manage-btn" :class="{ active: manageMode }" @tap="toggleManage">
        {{ manageMode ? '完成' : '管理' }}
      </view>
    </view>

    <view class="tabs-row">
      <text class="tab active">全部</text>
    </view>

    <EmptyState v-if="!items.length" title="购物车为空" description="先去商品页加入商品。" />
    <view v-else class="cart-list">
      <uni-swipe-action>
        <uni-swipe-action-item
          v-for="item in items"
          :key="itemKey(item)"
          :right-options="swipeOptions"
          @click="onSwipeClick($event, item)"
        >
          <view class="cart-card">
            <view class="goods-row">
              <view class="check-wrap">
                <view class="check-dot" :class="{ checked: isSelected(item) }" @tap.stop="toggleItem(item)">
                  <uni-icons v-if="isSelected(item)" type="checkmarkempty" size="17" color="#ffffff" />
                </view>
              </view>

              <view class="thumb" @tap="goProduct(item)">
                <image v-if="item.productImage || item.imageUrl" :src="item.productImage || item.imageUrl" mode="aspectFill" />
                <uni-icons v-else type="image" size="26" color="#98a2b3" />
              </view>

              <view class="goods-info">
                <text class="goods-title" @tap="goProduct(item)">{{ item.productTitle || item.title || '购物车商品' }}</text>
                <view class="sku-pill">
                  <text>{{ item.skuProperties || item.skuText || '默认规格' }}</text>
                  <uni-icons type="bottom" size="11" color="#98a2b3" />
                </view>
                <view class="price-row">
                  <view class="price-box">
                    <text class="yen">¥</text>
                    <text class="item-price">{{ itemPrice(item).toFixed(2) }}</text>
                  </view>
                  <view class="qty-box">
                    <text class="qty-btn" @tap.stop="minus(item)">-</text>
                    <text class="qty-num">{{ item.quantity || 1 }}</text>
                    <text class="qty-btn plus" @tap.stop="plus(item)">+</text>
                  </view>
                </view>
              </view>
            </view>
          </view>
        </uni-swipe-action-item>
      </uni-swipe-action>
    </view>

    <view class="checkout-bar">
      <view class="select-all" @tap="toggleAll">
        <view class="check-dot bar-check" :class="{ checked: allSelected }">
          <uni-icons v-if="allSelected" type="checkmarkempty" size="14" color="#ffffff" />
        </view>
        <text>全选</text>
      </view>

      <view v-if="!manageMode" class="settle-right">
        <view class="summary-inline">
          <text class="summary-label">合计</text>
          <text class="summary-money">¥{{ totalAmount.toFixed(2) }}</text>
        </view>
        <button class="checkout-button" @tap="goCheckout">去结算</button>
      </view>

      <view v-else class="settle-right manage-right">
        <button class="delete-button" @tap="deleteSelected">删除({{ selectedCount }})</button>
      </view>
    </view>
  </view>
</template>

<script>
import EmptyState from '../../components/EmptyState.vue'
import cartStore from '../../store/cart'
import { requireLoginFromProtectedTab } from '../../utils/routeGuard'

export default {
  components: { EmptyState },
  data() {
    return {
      items: this.createMockItems(),
      selectedMap: {},
      manageMode: false,
      swipeOptions: [
        { text: '删除', style: { backgroundColor: '#ef4444', color: '#ffffff' } }
      ]
    }
  },
  computed: {
    selectedCount() { return this.items.filter((item) => this.isSelected(item)).length },
    allSelected() { return this.items.length > 0 && this.selectedCount === this.items.length },
    totalAmount() {
      return this.items.reduce((sum, item) => {
        return this.isSelected(item) ? sum + this.itemPrice(item) * Number(item.quantity || 1) : sum
      }, 0)
    }
  },
  onShow() {
    if (!requireLoginFromProtectedTab('/pages/cart/cart')) return
    if (!this.items.length) this.items = this.createMockItems()
    this.initSelection()
  },
  methods: {
    createMockItems() {
      return [
        {
          id: 'mock-1',
          productId: 1,
          productTitle: 'Vidda 海信电视 65 英寸 R65 144Hz 高刷 4K 护眼电视',
          skuText: '65英寸 / 推荐观距2米 / 官方标配',
          price: 1869.15,
          quantity: 1,
          imageUrl: ''
        },
        {
          id: 'mock-2',
          productId: 2,
          productTitle: '百草园搬家打包袋 行李袋编织袋 大容量收纳袋',
          skuText: '蓝色 / 2个装 / 加厚款',
          price: 24.90,
          quantity: 2,
          imageUrl: ''
        },
        {
          id: 'mock-3',
          productId: 3,
          productTitle: 'BIAZE 毕亚兹 Type-C 数据线 快充耐用编织线',
          skuText: '1.5米 / 灰色 / 单条装',
          price: 19.90,
          quantity: 1,
          imageUrl: ''
        }
      ]
    },
    itemKey(item) { return item.id || `${item.productId || item.product?.id || 'p'}-${item.skuId || 'default'}` },
    itemPrice(item) { return Number(item.price || item.productPrice || item.basePrice || item.product?.basePrice || 0) },
    itemProductId(item) { return item.productId || item.product?.id || item.id },
    initSelection() {
      const next = {}
      this.items.forEach((item) => {
        const key = this.itemKey(item)
        next[key] = Object.prototype.hasOwnProperty.call(this.selectedMap, key) ? this.selectedMap[key] : false
      })
      this.selectedMap = next
    },
    isSelected(item) { return Boolean(this.selectedMap[this.itemKey(item)]) },
    toggleItem(item) {
      const key = this.itemKey(item)
      const next = { ...this.selectedMap }
      next[key] = !Boolean(next[key])
      this.selectedMap = next
    },
    toggleAll() {
      const checked = !this.allSelected
      const next = {}
      this.items.forEach((item) => { next[this.itemKey(item)] = checked })
      this.selectedMap = next
    },
    toggleManage() {
      this.manageMode = !this.manageMode
    },
    removeLocal(item) {
      const key = this.itemKey(item)
      this.items = this.items.filter((entry) => this.itemKey(entry) !== key)
      const next = { ...this.selectedMap }
      delete next[key]
      this.selectedMap = next
      cartStore.state.items = this.items
      uni.showToast({ title: '已删除', icon: 'none' })
    },
    onSwipeClick(event, item) {
      this.removeLocal(item)
    },
    deleteSelected() {
      if (!this.selectedCount) {
        uni.showToast({ title: '请选择要删除的商品', icon: 'none' })
        return
      }
      const selectedKeys = this.items.filter((item) => this.isSelected(item)).map((item) => this.itemKey(item))
      this.items = this.items.filter((item) => !selectedKeys.includes(this.itemKey(item)))
      this.selectedMap = {}
      cartStore.state.items = this.items
      uni.showToast({ title: '已删除选中商品', icon: 'none' })
    },
    minus(item) { uni.showToast({ title: '数量修改后续接入', icon: 'none' }) },
    plus(item) { uni.showToast({ title: '数量修改后续接入', icon: 'none' }) },
    goProduct(item) {
      const id = this.itemProductId(item)
      if (id) uni.navigateTo({ url: `/pages/product-detail/product-detail?id=${id}` })
    },
    goCheckout() {
      if (!this.selectedCount) {
        uni.showToast({ title: '请选择要结算的商品', icon: 'none' })
        return
      }
      uni.navigateTo({ url: '/pages/order-confirm/order-confirm' })
    }
  }
}
</script>

<style scoped>
.cart-page {
  padding: 22rpx 22rpx 190rpx;
}
.cart-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12rpx 4rpx 22rpx;
}
.top-main {
  display: flex;
  align-items: baseline;
  gap: 8rpx;
}
.cart-title-main {
  color: #1f2937;
  font-size: 44rpx;
  font-weight: 900;
}
.cart-count {
  color: #344054;
  font-size: 26rpx;
  font-weight: 700;
}
.manage-btn {
  padding: 12rpx 24rpx;
  border-radius: 999rpx;
  background: #ffffff;
  color: #14b8a6;
  font-size: 27rpx;
  font-weight: 800;
  box-shadow: 0 8rpx 22rpx rgba(15, 118, 110, 0.07);
}
.manage-btn.active {
  background: #fff7ed;
  color: #f97316;
}
.tabs-row {
  display: flex;
  align-items: center;
  padding: 12rpx 8rpx 24rpx;
}
.tab {
  color: #344054;
  font-size: 32rpx;
  font-weight: 800;
}
.tab.active {
  color: #14b8a6;
  position: relative;
}
.tab.active::after {
  content: '';
  position: absolute;
  left: 4rpx;
  right: 4rpx;
  bottom: -12rpx;
  height: 6rpx;
  border-radius: 999rpx;
  background: #f97316;
}
.cart-list {
  display: flex;
  flex-direction: column;
}
.cart-card {
  margin-bottom: 20rpx;
  padding: 24rpx;
  border-radius: 28rpx;
  background: #ffffff;
  box-shadow: 0 10rpx 28rpx rgba(15, 118, 110, 0.07);
}
.goods-row {
  display: flex;
  gap: 18rpx;
  align-items: flex-start;
}
.check-wrap {
  padding-top: 48rpx;
}
.check-dot {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42rpx;
  height: 42rpx;
  border-radius: 50%;
  border: 2rpx solid #cbd5d3;
  background: #ffffff;
  box-sizing: border-box;
}
.check-dot.checked {
  border-color: #14b8a6;
  background: #14b8a6;
}
.bar-check {
  width: 36rpx;
  height: 36rpx;
}
.thumb {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 176rpx;
  height: 176rpx;
  border-radius: 20rpx;
  background: #f4f8f8;
  overflow: hidden;
}
.thumb image {
  width: 100%;
  height: 100%;
}
.goods-info {
  flex: 1;
  min-width: 0;
}
.goods-title {
  display: -webkit-box;
  overflow: hidden;
  color: #1f2937;
  font-size: 29rpx;
  font-weight: 800;
  line-height: 1.35;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.sku-pill {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  max-width: 100%;
  margin-top: 12rpx;
  padding: 8rpx 14rpx;
  border-radius: 999rpx;
  background: #f4f8f8;
  color: #667085;
  font-size: 22rpx;
}
.price-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 24rpx;
}
.price-box {
  display: flex;
  align-items: baseline;
  color: #f97316;
}
.yen {
  font-size: 24rpx;
  font-weight: 900;
}
.item-price {
  font-size: 38rpx;
  font-weight: 900;
}
.qty-box {
  display: flex;
  align-items: center;
  overflow: hidden;
  border-radius: 999rpx;
  background: #f3f4f6;
}
.qty-btn,
.qty-num {
  min-width: 52rpx;
  height: 46rpx;
  text-align: center;
  color: #667085;
  font-size: 26rpx;
  line-height: 46rpx;
  font-weight: 800;
}
.qty-btn.plus {
  color: #1f2937;
}
.qty-num {
  min-width: 64rpx;
  color: #1f2937;
  background: #ffffff;
}
.checkout-bar {
  position: fixed;
  right: 0;
  bottom: 100rpx;
  left: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  min-height: 92rpx;
  padding: 14rpx 22rpx calc(14rpx + env(safe-area-inset-bottom));
  background: rgba(255,255,255,0.99);
  box-shadow: 0 -8rpx 28rpx rgba(15, 118, 110, 0.08);
  z-index: 20;
}
.select-all {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex: 0 0 auto;
  color: #344054;
  font-size: 27rpx;
}
.settle-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16rpx;
  flex: 1;
  min-width: 0;
}
.manage-right {
  justify-content: flex-end;
}
.summary-inline {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  min-width: 0;
}
.summary-label {
  margin-right: 8rpx;
  color: #344054;
  font-size: 25rpx;
  font-weight: 700;
}
.summary-money {
  color: #f97316;
  font-size: 38rpx;
  font-weight: 900;
}
.checkout-button,
.delete-button {
  flex: 0 0 auto;
  width: 210rpx;
  height: 78rpx;
  padding: 0;
  border-radius: 18rpx;
  color: #ffffff;
  font-size: 31rpx;
  font-weight: 900;
  line-height: 78rpx;
}
.checkout-button {
  background: linear-gradient(135deg, #f97316, #fb923c);
  box-shadow: 0 10rpx 24rpx rgba(249, 115, 22, 0.24);
}
.delete-button {
  background: linear-gradient(135deg, #ef4444, #f97316);
  box-shadow: 0 10rpx 24rpx rgba(239, 68, 68, 0.22);
}
</style>


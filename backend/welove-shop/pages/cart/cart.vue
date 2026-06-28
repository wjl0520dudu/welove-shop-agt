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

    <view v-if="loading" class="loading-wrap">
      <uni-load-more status="loading" :contentText="loadText" />
    </view>

    <view v-else-if="errorMessage" class="state-wrap">
      <EmptyState title="购物车加载失败" :description="errorMessage" />
      <button class="retry" @tap="loadCartItems">重新加载</button>
    </view>

    <EmptyState v-else-if="!items.length" title="购物车为空" description="先去商品页加入商品。" />
    <view v-else class="cart-list">
      <view class="shop-head" @tap="toggleAll">
        <view class="check-dot shop-check" :class="{ checked: allSelected }">
          <uni-icons v-if="allSelected" type="checkmarkempty" size="14" color="#ffffff" />
        </view>
        <uni-icons type="shop" size="18" color="#14b8a6" />
        <text class="shop-name">优选商城</text>
        <uni-icons type="right" size="14" color="#98a2b3" />
      </view>

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
                <image v-if="itemImage(item) && !imageErrorMap[itemKey(item)]" :src="itemImage(item)" mode="aspectFill" @error="markImageError(item)" />
                <uni-icons v-else type="image" size="26" color="#98a2b3" />
              </view>

              <view class="goods-info">
                <text class="goods-title" @tap="goProduct(item)">{{ itemTitle(item) }}</text>
                <view class="sku-pill" @tap.stop="openSkuSheet(item)">
                  <text>{{ itemSkuText(item) }}</text>
                  <uni-icons type="bottom" size="11" color="#98a2b3" />
                </view>
                <view class="price-row">
                  <view class="price-box">
                    <text class="item-price">{{ itemMoney(item) }}</text>
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
          <text class="summary-money">{{ formatMoney(totalAmount) }}</text>
        </view>
        <button class="checkout-button" :class="{ disabled: !selectedCount }" @tap="goCheckout">{{ selectedCount ? `结算(${selectedCount})` : '去结算' }}</button>
      </view>

      <view v-else class="settle-right manage-right">
        <button class="delete-button" @tap="deleteSelected">删除({{ selectedCount }})</button>
      </view>
    </view>

    <ProductSkuSheet
      :visible="showSkuSheet"
      :skus="editingSkus"
      @close="closeSkuSheet"
      @confirm="confirmSkuChange"
    />
  </view>
</template>

<script>
import EmptyState from '../../components/EmptyState.vue'
import ProductSkuSheet from '../../components/ProductSkuSheet.vue'
import cartStore from '../../store/cart'
import { removeCart, removeCartById, updateQuantity, updateSku, checkAll } from '../../api/cart'
import { getProductSkus } from '../../api/product'
import { formatMoney } from '../../utils/format'
import { buildImageUrl } from '../../utils/image'
import { requireLoginFromProtectedTab } from '../../utils/routeGuard'

export default {
  components: { EmptyState, ProductSkuSheet },
  data() {
    return {
      items: [],
      loading: false,
      errorMessage: '',
      selectedMap: {},
      imageErrorMap: {},
      showSkuSheet: false,
      editingItem: null,
      editingSkus: [],
      manageMode: false,
      swipeOptions: [
        { text: '删除', style: { backgroundColor: '#ef4444', color: '#ffffff' } }
      ],
      loadText: {
        contentdown: '加载更多',
        contentrefresh: '正在加载...',
        contentnomore: '没有更多了'
      }
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
    this.loadCartItems()
  },
  onPullDownRefresh() {
    this.loadCartItems().finally(() => uni.stopPullDownRefresh())
  },
  methods: {
    formatMoney(value) { return formatMoney(value) },
    async loadCartItems() {
      this.loading = true
      try {
        const list = await cartStore.loadCart()
        this.errorMessage = ''
        this.items = Array.isArray(list) ? list : []
        this.initSelection()
        this.syncTabBadge()
      } catch (error) {
        this.items = []
        this.selectedMap = {}
        uni.showToast({ title: '购物车加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    itemKey(item) { return item.cartItemId || item.cartId || item.id || `${item.productId || item.product?.id || 'p'}-${item.skuId || 'default'}` },
    itemPrice(item) { return Number(item.price || item.productPrice || item.skuPrice || item.sku?.price || item.basePrice || item.product?.basePrice || item.product?.price || 0) },
    itemMoney(item) { return formatMoney(this.itemPrice(item)) },
    itemTitle(item) { return item.productTitle || item.title || item.productName || item.product?.title || item.product?.name || '购物车商品' },
    itemImage(item) { return buildImageUrl(item.productImage || item.imageUrl || item.product?.imageUrl || item.product?.productImage || '') },
    itemSkuText(item) {
      const value = item.skuProperties || item.skuText || item.skuName || item.sku?.properties
      if (!value) return '默认规格'
      if (typeof value === 'string') return value
      return Object.keys(value).map((key) => `${key}: ${value[key]}`).join('  ') || '默认规格'
    },
    itemProductId(item) { return item.productId || item.product?.id || item.product?.productId },
    itemCartId(item) { return item.cartItemId || item.cartId || item.id },
    itemSkuId(item) { return item.skuId || item.sku?.id || null },
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
    async toggleAll() {
      const checked = !this.allSelected
      const next = {}
      this.items.forEach((item) => { next[this.itemKey(item)] = checked })
      this.selectedMap = next
      try {
        await checkAll(checked)
      } catch (error) {
        uni.showToast({ title: '全选状态同步失败', icon: 'none' })
      }
    },
    toggleManage() {
      this.manageMode = !this.manageMode
    },
    async removeRemote(item) {
      try {
        const cartItemId = this.itemCartId(item)
        if (cartItemId) await removeCartById(cartItemId)
        else await removeCart(this.itemProductId(item), Number(item.quantity || 1))
        await this.loadCartItems()
        uni.showToast({ title: '已删除', icon: 'none' })
      } catch (error) {
        uni.showToast({ title: '删除失败', icon: 'none' })
      }
    },
    onSwipeClick(event, item) {
      this.removeRemote(item)
    },
    async deleteSelected() {
      if (!this.selectedCount) {
        uni.showToast({ title: '请选择要删除的商品', icon: 'none' })
        return
      }
      const selected = this.items.filter((item) => this.isSelected(item))
      try {
        await Promise.all(selected.map((item) => {
          const cartItemId = this.itemCartId(item)
          return cartItemId ? removeCartById(cartItemId) : removeCart(this.itemProductId(item), Number(item.quantity || 1))
        }))
        this.selectedMap = {}
        await this.loadCartItems()
        uni.showToast({ title: '已删除选中商品', icon: 'none' })
      } catch (error) {
        uni.showToast({ title: '删除失败', icon: 'none' })
      }
    },
    async minus(item) {
      const quantity = Number(item.quantity || 1)
      if (quantity <= 1) {
        await this.removeRemote(item)
        return
      }
      await this.changeQuantity(item, quantity - 1)
    },
    async plus(item) {
      const quantity = Number(item.quantity || 1)
      await this.changeQuantity(item, quantity + 1)
    },
    async changeQuantity(item, quantity) {
      try {
        await updateQuantity(this.itemProductId(item), quantity)
        await this.loadCartItems()
        this.syncTabBadge()
      } catch (error) {
        uni.showToast({ title: '数量修改失败', icon: 'none' })
      }
    },
    markImageError(item) {
      this.imageErrorMap = { ...this.imageErrorMap, [this.itemKey(item)]: true }
    },
    syncTabBadge() {
      const count = this.items.reduce((sum, item) => sum + Number(item.quantity || 0), 0)
      cartStore.state.count = count
      if (count > 0) {
        uni.setTabBarBadge({ index: 2, text: String(count > 99 ? '99+' : count) })
      } else {
        uni.removeTabBarBadge({ index: 2 })
      }
    },
    async openSkuSheet(item) {
      const productId = this.itemProductId(item)
      if (!productId) return
      try {
        const skus = await getProductSkus(productId)
        this.editingItem = item
        this.editingSkus = Array.isArray(skus) ? skus : []
        if (!this.editingSkus.length) {
          uni.showToast({ title: '暂无可切换规格', icon: 'none' })
          return
        }
        this.showSkuSheet = true
      } catch (error) {
        uni.showToast({ title: '获取规格失败', icon: 'none' })
      }
    },
    closeSkuSheet() {
      this.showSkuSheet = false
      this.editingItem = null
      this.editingSkus = []
    },
    async confirmSkuChange(sku) {
      const item = this.editingItem
      if (!item || !sku?.id) return
      try {
        await updateSku(this.itemProductId(item), this.itemSkuId(item) || 0, sku.id)
        this.closeSkuSheet()
        await this.loadCartItems()
        uni.showToast({ title: '规格已更新', icon: 'none' })
      } catch (error) {
        uni.showToast({ title: '规格更新失败', icon: 'none' })
      }
    },
    goProduct(item) {
      const id = this.itemProductId(item)
      if (id) uni.navigateTo({ url: `/pages/product-detail/product-detail?id=${id}` })
    },
    goCheckout() {
      if (!this.selectedCount) {
        uni.showToast({ title: '请选择要结算的商品', icon: 'none' })
        return
      }
      const ids = this.items.filter((item) => this.isSelected(item)).map((item) => this.itemCartId(item)).filter(Boolean).join(',')
      uni.navigateTo({ url: `/pages/order-confirm/order-confirm?cartItemIds=${ids}` })
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
.loading-wrap,
.state-wrap {
  padding: 80rpx 0;
}
.retry {
  width: 240rpx;
  height: 72rpx;
  margin: 12rpx auto 0;
  border-radius: 999rpx;
  background: #14b8a6;
  color: #ffffff;
  font-size: 27rpx;
}
.shop-head {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 0;
  padding: 22rpx 24rpx;
  border-radius: 24rpx 24rpx 0 0;
  background: #ffffff;
  box-shadow: 0 10rpx 28rpx rgba(15, 118, 110, 0.05);
}
.shop-check {
  width: 36rpx;
  height: 36rpx;
}
.shop-name {
  flex: 1;
  color: #1f2937;
  font-size: 28rpx;
  font-weight: 800;
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
.checkout-button.disabled {
  opacity: 0.55;
}
.delete-button {
  background: linear-gradient(135deg, #ef4444, #f97316);
  box-shadow: 0 10rpx 24rpx rgba(239, 68, 68, 0.22);
}
</style>



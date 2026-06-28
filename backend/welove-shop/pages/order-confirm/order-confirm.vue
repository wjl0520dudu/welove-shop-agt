<template>
  <view class="page checkout-page">
    <view v-if="loading" class="loading-wrap">
      <uni-load-more status="loading" :contentText="loadText" />
    </view>

    <view v-else class="content">
      <view class="address-card" @tap="chooseAddress">
        <uni-icons type="location" size="22" color="#14b8a6" />
        <view v-if="address" class="address-main">
          <view class="address-head">
            <text class="receiver">{{ receiverName || address.receiverName }}</text>
            <text class="phone">{{ receiverPhone || address.phone }}</text>
            <text v-if="isDefault(address)" class="default-tag">默认</text>
          </view>
          <text class="address-text">{{ fullAddress(address) }}</text>
        </view>
        <view v-else class="address-empty"><text>请选择收货地址</text></view>
        <uni-icons type="right" size="16" color="#98a2b3" />
      </view>

      <view class="form-card">
        <text class="section-title">收货人信息</text>
        <view class="input-row">
          <text class="input-label">姓名</text>
          <input class="input" v-model.trim="receiverName" placeholder="收货人姓名" maxlength="30" />
        </view>
        <view class="input-row">
          <text class="input-label">手机号</text>
          <input class="input" v-model.trim="receiverPhone" placeholder="收货人手机号" type="number" maxlength="11" />
        </view>
      </view>

      <view class="goods-card">
        <text class="section-title">商品信息</text>
        <view v-if="!checkoutItems.length" class="empty-goods">无商品信息</view>
        <view v-for="item in checkoutItems" :key="item.key" class="goods-row">
          <view class="thumb" @tap="goProduct(item)">
            <image v-if="item.image && !imageErrorMap[item.key]" :src="item.image" mode="aspectFill" @error="markImageError(item)" />
            <uni-icons v-else type="image" size="24" color="#98a2b3" />
          </view>
          <view class="goods-info">
            <text class="goods-title">{{ item.title }}</text>
            <text v-if="item.skuText && item.skuText !== '默认规格'" class="sku-text">{{ item.skuText }}</text>
            <view class="price-line">
              <text class="price">{{ formatMoney(item.price) }}</text>
              <text class="qty">x{{ item.quantity }}</text>
            </view>
          </view>
        </view>
      </view>

      <view class="remark-card">
        <text class="section-title">订单备注</text>
        <textarea class="remark" v-model.trim="remark" placeholder="选填，有什么要交代的" maxlength="120" />
      </view>

      <view class="summary-card">
        <view class="summary-row"><text>商品金额</text><text>{{ formatMoney(itemsTotal) }}</text></view>
        <view class="summary-row"><text>运费</text><text>{{ freightAmount > 0 ? formatMoney(freightAmount) : '免运费' }}</text></view>
        <view class="divider"></view>
        <view class="summary-row total"><text>合计</text><text>{{ formatMoney(payAmount) }}</text></view>
      </view>
    </view>

    <view class="submit-bar">
      <view>
        <text class="pay-label">实付金额</text>
        <text class="pay-money">{{ formatMoney(payAmount) }}</text>
      </view>
      <button class="submit-btn" :disabled="submitting || !canSubmit" @tap="submit">
        {{ submitting ? '提交中...' : '提交订单' }}
      </button>
    </view>
  </view>
</template>

<script>
import { getAddressList } from '../../api/address'
import { getCartList, removeCartById } from '../../api/cart'
import { createOrder } from '../../api/order'
import { getProductDetail, getProductSkus } from '../../api/product'
import { formatMoney } from '../../utils/format'
import { buildImageUrl, pickProductImage } from '../../utils/image'
import { requireLogin } from '../../utils/routeGuard'
import cartStore from '../../store/cart'

export default {
  data() {
    return {
      source: 'cart',
      cartItemIds: [],
      productId: null,
      skuId: null,
      quantity: 1,
      address: null,
      checkoutItems: [],
      receiverName: '',
      receiverPhone: '',
      remark: '',
      freightAmount: 0,
      loading: false,
      submitting: false,
      imageErrorMap: {},
      loadText: { contentdown: '加载更多', contentrefresh: '正在加载...', contentnomore: '没有更多了' }
    }
  },
  computed: {
    itemsTotal() { return this.checkoutItems.reduce((sum, item) => sum + Number(item.price || 0) * Number(item.quantity || 1), 0) },
    payAmount() { return this.itemsTotal + Number(this.freightAmount || 0) },
    canSubmit() { return Boolean(this.address?.id && this.checkoutItems.length && this.receiverName && this.receiverPhone) }
  },
  onLoad(query = {}) {
    if (!requireLogin('/pages/order-confirm/order-confirm')) return
    this.parseQuery(query)
    this.loadCheckout()
  },
  onShow() {
    if (!requireLogin('/pages/order-confirm/order-confirm')) return
    const selected = uni.getStorageSync('selectedAddress')
    if (selected && selected.id) {
      this.applyAddress(selected)
      uni.removeStorageSync('selectedAddress')
    }
  },
  methods: {
    formatMoney(value) { return formatMoney(value) },
    parseQuery(query) {
      if (query.cartItemIds) {
        this.source = 'cart'
        this.cartItemIds = String(query.cartItemIds).split(',').map(id => Number(id)).filter(Boolean)
      } else if (query.productId) {
        this.source = 'buyNow'
        this.productId = Number(query.productId)
        this.skuId = query.skuId ? Number(query.skuId) : null
        this.quantity = Math.max(Number(query.quantity || 1), 1)
      }
    },
    async loadCheckout() {
      this.loading = true
      try {
        await Promise.all([this.loadDefaultAddress(), this.loadCheckoutItems()])
      } finally {
        this.loading = false
      }
    },
    async loadDefaultAddress() {
      try {
        const list = await getAddressList()
        const addresses = Array.isArray(list) ? list : []
        this.applyAddress(addresses.find(item => this.isDefault(item)) || addresses[0] || null)
      } catch (error) {
        uni.showToast({ title: '地址加载失败', icon: 'none' })
      }
    },
    applyAddress(address) {
      this.address = address
      if (address) {
        this.receiverName = address.receiverName || this.receiverName
        this.receiverPhone = address.phone || this.receiverPhone
      }
    },
    async loadCheckoutItems() {
      try {
        if (this.source === 'buyNow') await this.loadBuyNowItem()
        else await this.loadCartItems()
      } catch (error) {
        this.checkoutItems = []
        uni.showToast({ title: '商品加载失败', icon: 'none' })
      }
    },
    async loadCartItems() {
      const data = await getCartList()
      const list = Array.isArray(data) ? data : (data?.records || data?.items || data?.list || [])
      const selectedIds = new Set(this.cartItemIds)
      const selected = this.cartItemIds.length ? list.filter(item => selectedIds.has(Number(this.itemCartId(item)))) : list
      this.checkoutItems = selected.map(item => this.normalizeCartItem(item)).filter(item => item.productId)
    },
    async loadBuyNowItem() {
      if (!this.productId) return
      const [detail, skus] = await Promise.all([
        getProductDetail(this.productId),
        getProductSkus(this.productId).catch(() => [])
      ])
      const product = detail?.product || detail || {}
      const skuList = Array.isArray(detail?.skus) && detail.skus.length ? detail.skus : (Array.isArray(skus) ? skus : [])
      const sku = this.skuId ? skuList.find(item => Number(item.id) === Number(this.skuId)) : null
      this.checkoutItems = [{
        key: `buy-${this.productId}-${this.skuId || 'default'}`,
        productId: this.productId,
        skuId: this.skuId,
        title: product.title || product.name || '订单商品',
        image: buildImageUrl(pickProductImage(product)),
        skuText: sku ? this.formatSku(sku) : '默认规格',
        price: Number(sku?.price || product.basePrice || product.price || 0),
        quantity: this.quantity
      }]
    },
    normalizeCartItem(item) {
      return {
        key: `cart-${this.itemCartId(item) || this.itemProductId(item)}`,
        cartItemId: this.itemCartId(item),
        productId: this.itemProductId(item),
        skuId: this.itemSkuId(item),
        title: item.productTitle || item.title || item.productName || item.product?.title || item.product?.name || '订单商品',
        image: buildImageUrl(item.productImage || item.imageUrl || item.product?.imageUrl || item.product?.productImage || ''),
        skuText: this.itemSkuText(item),
        price: Number(item.price || item.productPrice || item.skuPrice || item.sku?.price || item.basePrice || item.product?.basePrice || item.product?.price || 0),
        quantity: Number(item.quantity || 1)
      }
    },
    itemCartId(item) { return item.cartItemId || item.cartId || item.id },
    itemProductId(item) { return item.productId || item.product?.id || item.product?.productId },
    itemSkuId(item) { return item.skuId || item.sku?.id || null },
    itemSkuText(item) {
      const value = item.skuProperties || item.skuText || item.skuName || item.sku?.properties
      if (!value) return '默认规格'
      if (typeof value === 'string') return value
      return Object.keys(value).map(key => `${key}: ${value[key]}`).join('  ') || '默认规格'
    },
    formatSku(sku) {
      const properties = sku.properties || {}
      if (typeof properties === 'string') return properties || '默认规格'
      return Object.keys(properties).map(key => `${key}: ${properties[key]}`).join('  ') || sku.skuCode || '默认规格'
    },
    isDefault(item) { return item?.isDefault === 1 || item?.isDefault === true },
    fullAddress(item) { return `${item.province || ''}${item.city || ''}${item.district || ''}${item.detail || ''}` },
    chooseAddress() { uni.navigateTo({ url: '/pages/address-list/address-list?select=1' }) },
    markImageError(item) { this.imageErrorMap = { ...this.imageErrorMap, [item.key]: true } },
    goProduct(item) { if (item.productId) uni.navigateTo({ url: `/pages/product-detail/product-detail?id=${item.productId}` }) },
    validate() {
      if (!this.address?.id) return '请选择收货地址'
      if (!this.receiverName) return '请输入收货人姓名'
      if (!/^1\d{10}$/.test(this.receiverPhone)) return '请输入正确手机号'
      if (!this.checkoutItems.length) return '请选择要购买的商品'
      return ''
    },
    async cleanupCheckedCartItems() {
      if (this.source !== 'cart' || !this.cartItemIds.length) return
      await Promise.allSettled(this.cartItemIds.map(id => removeCartById(id)))
    },
    async submit() {
      const message = this.validate()
      if (message) {
        uni.showToast({ title: message, icon: 'none' })
        return
      }
      this.submitting = true
      try {
        const order = await createOrder({
          addressId: this.address.id,
          items: this.checkoutItems.map(item => ({ productId: item.productId, skuId: item.skuId, quantity: item.quantity })),
          remark: this.remark || null,
          receiverName: this.receiverName,
          receiverPhone: this.receiverPhone
        })
        uni.showToast({ title: '订单已创建', icon: 'none' })
        await this.cleanupCheckedCartItems()
        cartStore.refreshCount().catch(() => {})
        const orderId = order?.id || order?.orderId
        setTimeout(() => {
          if (orderId) uni.redirectTo({ url: `/pages/order-detail/order-detail?id=${orderId}` })
          else uni.redirectTo({ url: '/pages/order-list/order-list' })
        }, 350)
      } catch (error) {
        uni.showToast({ title: error.message || '创建订单失败', icon: 'none' })
      } finally {
        this.submitting = false
      }
    }
  }
}
</script>

<style scoped>
.checkout-page{min-height:100vh;padding:22rpx 22rpx 150rpx}.loading-wrap{padding:120rpx 0}.content{display:flex;flex-direction:column;gap:18rpx}.address-card,.form-card,.goods-card,.remark-card,.summary-card{border-radius:22rpx;background:#fff;box-shadow:0 10rpx 28rpx rgba(15,118,110,.06)}.address-card{display:flex;align-items:center;gap:16rpx;padding:24rpx}.address-main{flex:1;min-width:0}.address-head{display:flex;align-items:center;gap:12rpx}.receiver{color:#1f2937;font-size:30rpx;font-weight:900}.phone{color:#667085;font-size:26rpx;font-weight:700}.default-tag{padding:4rpx 10rpx;border-radius:8rpx;background:#ccfbf1;color:#0f766e;font-size:22rpx;font-weight:800}.address-text{display:block;margin-top:10rpx;color:#344054;font-size:26rpx;line-height:1.45}.address-empty{flex:1;color:#ef4444;font-size:29rpx;font-weight:800}.form-card,.goods-card,.remark-card,.summary-card{padding:24rpx}.section-title{display:block;margin-bottom:16rpx;color:#1f2937;font-size:29rpx;font-weight:900}.input-row{display:flex;align-items:center;height:72rpx;border-top:1rpx solid #eef2f7}.input-row:first-of-type{border-top:0}.input-label{width:110rpx;color:#667085;font-size:26rpx;font-weight:700}.input{flex:1;color:#1f2937;font-size:28rpx}.empty-goods{padding:34rpx 0;color:#98a2b3;text-align:center;font-size:27rpx}.goods-row{display:flex;gap:18rpx;padding:18rpx 0;border-top:1rpx solid #eef2f7}.goods-row:first-of-type{border-top:0}.thumb{display:flex;align-items:center;justify-content:center;width:144rpx;height:144rpx;border-radius:18rpx;background:#f4f8f8;overflow:hidden}.thumb image{width:100%;height:100%}.goods-info{flex:1;min-width:0}.goods-title{display:-webkit-box;overflow:hidden;color:#1f2937;font-size:28rpx;font-weight:800;line-height:1.35;-webkit-line-clamp:2;-webkit-box-orient:vertical}.sku-text{display:block;margin-top:8rpx;color:#667085;font-size:23rpx}.price-line{display:flex;align-items:center;justify-content:space-between;margin-top:16rpx}.price{color:#f97316;font-size:31rpx;font-weight:900}.qty{color:#667085;font-size:25rpx;font-weight:700}.remark{width:100%;min-height:104rpx;color:#1f2937;font-size:27rpx;line-height:1.45}.summary-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:12rpx;color:#344054;font-size:27rpx}.summary-row.total{margin-bottom:0;color:#1f2937;font-size:30rpx;font-weight:900}.summary-row.total text:last-child{color:#f97316}.divider{height:1rpx;margin:12rpx 0;background:#eef2f7}.submit-bar{position:fixed;right:0;bottom:0;left:0;display:flex;align-items:center;justify-content:space-between;gap:20rpx;padding:16rpx 22rpx calc(16rpx + env(safe-area-inset-bottom));background:#fff;box-shadow:0 -8rpx 28rpx rgba(15,118,110,.08);z-index:20}.pay-label,.pay-money{display:block}.pay-label{color:#667085;font-size:23rpx}.pay-money{margin-top:4rpx;color:#f97316;font-size:36rpx;font-weight:900}.submit-btn{flex:0 0 auto;width:230rpx;height:78rpx;border-radius:999rpx;background:#14b8a6;color:#fff;font-size:30rpx;font-weight:900;line-height:78rpx}.submit-btn[disabled]{background:#98a2b3;color:#fff}
</style>

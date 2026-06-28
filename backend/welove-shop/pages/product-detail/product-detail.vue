<template>
  <view class="page">
    <view v-if="product" class="detail">
      <image v-if="product.imageUrl" class="hero" :src="product.imageUrl" mode="aspectFit" />
      <view v-else class="hero placeholder">暂无图片</view>
      <view class="section">
        <text class="brand">{{ product.brand || '精选商品' }}</text>
        <text class="title">{{ product.title }}</text>
        <text class="price">¥{{ Number(product.basePrice || 0).toFixed(2) }}</text>
        <text class="subtitle">评分 {{ product.rating || 0 }} · 销量 {{ product.salesCount || 0 }}</text>
      </view>
      <view v-if="product.description" class="section">
        <text class="section-title">商品描述</text>
        <text class="description">{{ product.description }}</text>
      </view>
      <view class="bottom-bar">
        <button class="secondary-button" @tap="handleAddCart">加入购物车</button>
        <button class="primary-button" @tap="goBuyNow">立即购买</button>
      </view>
    </view>
    <EmptyState v-else title="商品加载中" />
  </view>
</template>

<script>
import EmptyState from '../../components/EmptyState.vue'
import { getProductDetail } from '../../api/product'
import { addCart } from '../../api/cart'
import { recordBrowse } from '../../api/recommend'

export default {
  components: { EmptyState },
  data() {
    return { productId: null, product: null }
  },
  async onLoad(query) {
    this.productId = query.id
    const data = await getProductDetail(query.id)
    this.product = data.product || data
    recordBrowse({ productId: Number(query.id) }).catch(() => {})
  },
  methods: {
    async handleAddCart() {
      await addCart(this.productId)
      uni.showToast({ title: '已加入购物车', icon: 'success' })
    },
    goBuyNow() {
      uni.navigateTo({ url: `/pages/order-confirm/order-confirm?productId=${this.productId}` })
    }
  }
}
</script>

<style scoped>
.detail { padding-bottom: 128rpx; }
.hero { width: 100%; height: 560rpx; background: #eef2f6; }
.placeholder { display: flex; align-items: center; justify-content: center; color: #98a2b3; }
.brand { display: block; margin-bottom: 8rpx; color: #2563eb; font-size: 26rpx; }
.section-title { display: block; margin-bottom: 12rpx; font-weight: 700; }
.description { color: #475467; font-size: 28rpx; line-height: 1.6; }
.bottom-bar {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20rpx;
  padding: 20rpx 24rpx;
  background: #ffffff;
  box-shadow: 0 -8rpx 24rpx rgba(16, 24, 40, 0.08);
}
</style>

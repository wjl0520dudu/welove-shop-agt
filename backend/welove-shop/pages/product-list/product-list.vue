<template>
  <view class="page product-page">
    <view class="hero">
      <view class="hero-copy">
        <text class="eyebrow">WELoVE SHOP</text>
        <text class="hero-title">精选商品</text>
        <text class="hero-subtitle">青橙主题移动商城，按 Android 原型同步开发</text>
      </view>
      <view class="hero-badge">
        <uni-icons type="shop" size="28" color="#ffffff" />
      </view>
    </view>

    <view class="search-card">
      <uni-search-bar
        v-model="keyword"
        radius="100"
        placeholder="搜索商品、品牌、功效"
        bgColor="#f4f8f8"
        cancelButton="none"
        @confirm="loadProducts"
        @clear="loadProducts"
      />
    </view>

    <view class="category-row">
      <view class="category-chip active">全部</view>
      <view class="category-chip">美妆护肤</view>
      <view class="category-chip">数码电子</view>
      <view class="category-chip orange">食品生活</view>
    </view>

    <view class="toolbar">
      <text class="toolbar-title">为你推荐</text>
      <view class="refresh" @tap="loadProducts">
        <uni-icons type="refreshempty" size="16" color="#14b8a6" />
        <text>刷新</text>
      </view>
    </view>

    <view v-if="products.length" class="grid">
      <ProductCard v-for="item in products" :key="item.id" :product="item" @click="goDetail(item.id)" />
    </view>
    <EmptyState v-else title="暂无商品" description="后端启动并导入数据后，这里会显示商品列表。" />
  </view>
</template>

<script>
import ProductCard from '../../components/ProductCard.vue'
import EmptyState from '../../components/EmptyState.vue'
import { getProductList, searchProducts } from '../../api/product'

export default {
  components: { ProductCard, EmptyState },
  data() { return { keyword: '', products: [] } },
  onLoad() { this.loadProducts() },
  methods: {
    async loadProducts() {
      const data = this.keyword
        ? await searchProducts(this.keyword, 20)
        : await getProductList({ page: 1, size: 20 })
      this.products = Array.isArray(data) ? data : (data?.records || [])
    },
    goDetail(id) { uni.navigateTo({ url: `/pages/product-detail/product-detail?id=${id}` }) }
  }
}
</script>

<style scoped>
.product-page { padding: 24rpx 24rpx 140rpx; }
.hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 34rpx 30rpx;
  border-radius: 30rpx;
  background: linear-gradient(135deg, #0f766e 0%, #14b8a6 72%, #fed7aa 100%);
  box-shadow: 0 18rpx 42rpx rgba(20, 184, 166, 0.25);
}
.eyebrow { display: block; margin-bottom: 8rpx; color: rgba(255,255,255,0.76); font-size: 20rpx; letter-spacing: 1rpx; }
.hero-title { display: block; color: #ffffff; font-size: 42rpx; font-weight: 800; }
.hero-subtitle { display: block; margin-top: 8rpx; color: rgba(255,255,255,0.9); font-size: 24rpx; }
.hero-badge { display: flex; align-items: center; justify-content: center; width: 88rpx; height: 88rpx; border-radius: 50%; background: rgba(255,255,255,0.22); }
.search-card { margin: 24rpx 0 12rpx; border-radius: 999rpx; background: #ffffff; box-shadow: 0 10rpx 30rpx rgba(15, 118, 110, 0.07); }
.category-row { display: flex; gap: 16rpx; overflow-x: auto; padding: 16rpx 0 24rpx; white-space: nowrap; }
.category-chip { flex: 0 0 auto; padding: 14rpx 22rpx; border-radius: 999rpx; background: #ffffff; color: #475467; font-size: 24rpx; border: 1rpx solid #e0ece9; }
.category-chip.active { background: #14b8a6; border-color: #14b8a6; color: #ffffff; }
.category-chip.orange { color: #f97316; border-color: #fed7aa; background: #fff7ed; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
.toolbar-title { color: #1f2937; font-size: 32rpx; font-weight: 800; }
.refresh { display: flex; align-items: center; gap: 6rpx; color: #14b8a6; font-size: 26rpx; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20rpx; }
</style>

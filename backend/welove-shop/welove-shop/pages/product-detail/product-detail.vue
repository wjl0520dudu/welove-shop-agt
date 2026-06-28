<template>
  <view class="page detail-page">
    <view v-if="loading" class="state-page">
      <uni-load-more status="loading" :contentText="loadText" />
    </view>

    <view v-else-if="error" class="state-page">
      <EmptyState title="商品加载失败" :description="error" />
      <button class="retry" @tap="loadDetail">重新加载</button>
    </view>

    <view v-else-if="product" class="detail">
      <view class="image-section">
        <swiper v-if="visibleImages.length" class="swiper" circular :indicator-dots="visibleImages.length > 1" indicator-color="rgba(255,255,255,0.55)" indicator-active-color="#14b8a6">
          <swiper-item v-for="(item, index) in visibleImages" :key="index">
            <image class="hero" :src="item" mode="aspectFit" @error="markImageFailed(item)" />
          </swiper-item>
        </swiper>
        <view v-else class="hero placeholder">
          <uni-icons type="image" size="44" color="#98a2b3" />
          <text>暂无图片</text>
        </view>
      </view>

      <view class="info-card">
        <view class="brand-row">
          <text class="brand">{{ product.brand || product.subCategory || '精选商品' }}</text>
          <view class="favorite" :class="{ active: isFavorite }" @tap="toggleFavorite">
            <uni-icons type="heart-filled" size="20" :color="isFavorite ? '#f97316' : '#98a2b3'" />
            <text>{{ isFavorite ? '已收藏' : '收藏' }}</text>
          </view>
        </view>
        <text class="title">{{ product.title || product.name || '未命名商品' }}</text>
        <view class="price-row">
          <text class="price">¥{{ currentPrice }}</text>
          <text class="sales">{{ product.salesCount || 0 }} 人付款</text>
        </view>
        <view class="meta-row">
          <text>评分 {{ rating }}</text>
          <text>评价 {{ product.reviewCount || reviews.length || 0 }}</text>
          <text>库存 {{ selectedSku ? selectedSku.stock : totalStock }}</text>
        </view>
      </view>

      <view v-if="product.description" class="section">
        <text class="section-title">商品描述</text>
        <text class="description">{{ product.description }}</text>
      </view>

      <view class="section" @tap="openSku('select')">
        <view class="section-head">
          <text class="section-title">规格选择</text>
          <uni-icons type="right" size="16" color="#98a2b3" />
        </view>
        <view v-if="skus.length" class="selected-sku">
          <text>{{ selectedSkuText }}</text>
          <text class="selected-price">¥{{ currentPrice }}</text>
        </view>
        <text v-else class="muted">默认规格</text>
      </view>

      <view class="section">
        <view class="section-head">
          <text class="section-title">用户评价</text>
          <text class="count">{{ reviews.length }} 条</text>
        </view>
        <view v-if="reviews.length" class="review-list">
          <view v-for="item in reviews" :key="item.id" class="review-item">
            <view class="review-head">
              <text class="review-name">{{ item.isAnonymous ? '匿名用户' : (item.nickname || '匿名用户') }}</text>
              <text class="review-rating">{{ stars(item.rating) }}</text>
            </view>
            <text class="review-content">{{ item.content || '用户暂未填写评价内容' }}</text>
          </view>
        </view>
        <text v-else class="muted">暂无评价</text>
      </view>

      <view class="section">
        <view class="section-head">
          <text class="section-title">常见问题</text>
          <text class="count">{{ faqs.length }} 条</text>
        </view>
        <view v-if="faqs.length" class="faq-list">
          <view v-for="item in faqs" :key="item.id" class="faq-item">
            <text class="question">Q：{{ item.question }}</text>
            <text class="answer">A：{{ item.answer }}</text>
          </view>
        </view>
        <text v-else class="muted">暂无常见问题</text>
      </view>

      <view class="bottom-bar">
        <button class="secondary-button" @tap="openSku('cart')">加入购物车</button>
        <button class="primary-button" @tap="openSku('buy')">立即购买</button>
      </view>

      <ProductSkuSheet
        :visible="showSkuSheet"
        :skus="skus"
        @close="showSkuSheet = false"
        @confirm="confirmSku"
      />
    </view>

    <EmptyState v-else title="商品不存在" description="请返回商品列表重新选择。" />
  </view>
</template>

<script>
import EmptyState from '../../components/EmptyState.vue'
import ProductSkuSheet from '../../components/ProductSkuSheet.vue'
import { formatMoney } from '../../utils/format'
import { buildImageUrl, pickProductImage } from '../../utils/image'
import { getProductDetail, getProductSkus, getProductReviews, getProductFaqs, getProductImages } from '../../api/product'
import { addCart } from '../../api/cart'
import { addFavorite, removeFavorite, getFavoriteList, recordBrowse } from '../../api/recommend'
import { isLoggedIn } from '../../utils/auth'
import { toLogin } from '../../utils/routeGuard'
import cartStore from '../../store/cart'

export default {
  components: { EmptyState, ProductSkuSheet },
  data() {
    return {
      productId: null,
      product: null,
      skus: [],
      images: [],
      reviews: [],
      faqs: [],
      selectedSku: null,
      isFavorite: false,
      showSkuSheet: false,
      pendingAction: 'select',
      loading: false,
      error: '',
      imageErrorMap: {},
      loadText: {
        contentdown: '加载更多',
        contentrefresh: '正在加载...',
        contentnomore: '没有更多了'
      }
    }
  },
  computed: {
    displayImages() {
      const list = this.images.map(item => buildImageUrl(item.imageUrl || item.url)).filter(Boolean)
      const main = buildImageUrl(pickProductImage(this.product || {}))
      return Array.from(new Set([main, ...list].filter(Boolean)))
    },
    visibleImages() {
      return this.displayImages.filter(item => !this.imageErrorMap[item])
    },
    currentPrice() {
      return formatMoney(this.selectedSku?.price || this.product?.basePrice || this.product?.price || 0)
    },
    rating() {
      return Number(this.product?.rating || 0).toFixed(1)
    },
    totalStock() {
      if (!this.skus.length) return '-'
      return this.skus.reduce((sum, item) => sum + Number(item.stock || 0), 0)
    },
    selectedSkuText() {
      return this.selectedSku ? this.formatSku(this.selectedSku) : '请选择规格'
    }
  },
  async onLoad(query) {
    this.productId = Number(query.id)
    await this.loadDetail()
  },
  onShow() {
    if (this.productId && isLoggedIn()) this.loadFavoriteState()
  },
  methods: {
    async loadDetail() {
      if (!this.productId) return
      this.loading = true
      this.error = ''
      try {
        const detail = await getProductDetail(this.productId)
        this.applyDetail(detail)
        await this.fillMissingDetail()
        this.selectDefaultSku()
        this.loadFavoriteState()
        this.recordBrowseHistory()
      } catch (error) {
        this.error = error?.message || '请确认后端商品详情接口已启动。'
      } finally {
        this.loading = false
      }
    },
    applyDetail(detail = {}) {
      this.product = detail.product || detail
      this.skus = Array.isArray(detail.skus) ? detail.skus : []
      this.images = Array.isArray(detail.images) ? detail.images : []
      this.reviews = Array.isArray(detail.reviews) ? detail.reviews : []
      this.faqs = Array.isArray(detail.faqs) ? detail.faqs : []
    },
    async fillMissingDetail() {
      const tasks = []
      if (!this.skus.length) tasks.push(getProductSkus(this.productId).then(data => { this.skus = Array.isArray(data) ? data : [] }).catch(() => {}))
      if (!this.images.length) tasks.push(getProductImages(this.productId).then(data => { this.images = Array.isArray(data) ? data : [] }).catch(() => {}))
      if (!this.reviews.length) tasks.push(getProductReviews(this.productId, 10).then(data => { this.reviews = Array.isArray(data) ? data : [] }).catch(() => {}))
      if (!this.faqs.length) tasks.push(getProductFaqs(this.productId).then(data => { this.faqs = Array.isArray(data) ? data : [] }).catch(() => {}))
      if (tasks.length) await Promise.all(tasks)
    },
    selectDefaultSku() {
      if (!this.skus.length) {
        this.selectedSku = null
        return
      }
      this.selectedSku = this.skus.find(item => item.isDefault === true || item.isDefault === 1) || this.skus[0]
    },
    async loadFavoriteState() {
      if (!isLoggedIn()) {
        this.isFavorite = false
        return
      }
      try {
        const data = await getFavoriteList()
        const list = Array.isArray(data) ? data : (data?.records || [])
        this.isFavorite = list.some(item => Number(item.productId || item.product?.id || item.id) === Number(this.productId))
      } catch (error) {}
    },
    recordBrowseHistory() {
      if (!isLoggedIn()) return
      recordBrowse({ productId: this.productId, source: 'detail' }).catch(() => {})
    },
    async toggleFavorite() {
      if (!isLoggedIn()) {
        toLogin(`/pages/product-detail/product-detail?id=${this.productId}`)
        return
      }
      const previous = this.isFavorite
      this.isFavorite = !previous
      try {
        if (previous) await removeFavorite(this.productId)
        else await addFavorite(this.productId)
        await this.loadFavoriteState()
      } catch (error) {
        this.isFavorite = previous
        uni.showToast({ title: '收藏操作失败', icon: 'none' })
      }
    },
    openSku(action) {
      this.pendingAction = action
      if (this.skus.length) {
        this.showSkuSheet = true
        return
      }
      this.runAction(null)
    },
    confirmSku(sku) {
      this.selectedSku = sku
      this.showSkuSheet = false
      this.runAction(sku)
    },
    async runAction(sku) {
      if (this.pendingAction === 'select') return
      if (!isLoggedIn()) {
        toLogin(`/pages/product-detail/product-detail?id=${this.productId}`)
        return
      }
      if (this.pendingAction === 'cart') {
        await this.handleAddCart(sku)
      } else if (this.pendingAction === 'buy') {
        this.goBuyNow(sku)
      }
    },
    async handleAddCart(sku) {
      try {
        await addCart(this.productId, sku?.id)
        cartStore.refreshCount().catch(() => {})
        uni.showToast({ title: '已加入购物车', icon: 'success' })
      } catch (error) {
        uni.showToast({ title: '加入购物车失败', icon: 'none' })
      }
    },
    goBuyNow(sku) {
      const skuParam = sku?.id ? `&skuId=${sku.id}` : ''
      uni.navigateTo({ url: `/pages/order-confirm/order-confirm?productId=${this.productId}${skuParam}` })
    },
    markImageFailed(url) {
      this.imageErrorMap = { ...this.imageErrorMap, [url]: true }
    },
    formatSku(sku) {
      const properties = sku?.properties || {}
      if (typeof properties === 'string') return properties || '默认规格'
      const text = Object.keys(properties).map(key => `${key}: ${properties[key]}`).join('  ')
      return text || sku?.skuCode || '默认规格'
    },
    stars(rating) {
      const value = Math.max(1, Math.min(5, Number(rating || 5)))
      return '★'.repeat(value)
    }
  }
}
</script>

<style scoped>
.detail-page {
  min-height: 100vh;
  padding-bottom: 132rpx;
  background: #f6fbfa;
}
.state-page {
  padding: 120rpx 28rpx;
}
.retry {
  width: 260rpx;
  height: 76rpx;
  margin-top: 24rpx;
  border-radius: 999rpx;
  background: #14b8a6;
  color: #ffffff;
  font-size: 28rpx;
}
.image-section {
  background: #ffffff;
}
.swiper,
.hero {
  width: 100%;
  height: 600rpx;
}
.hero {
  background: #eef6f5;
}
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14rpx;
  color: #98a2b3;
  font-size: 26rpx;
}
.info-card,
.section {
  margin: 18rpx 24rpx 0;
  padding: 24rpx;
  border-radius: 18rpx;
  background: #ffffff;
  box-shadow: 0 8rpx 26rpx rgba(15, 118, 110, 0.06);
}
.brand-row,
.price-row,
.meta-row,
.section-head,
.review-head,
.selected-sku {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18rpx;
}
.brand {
  color: #0f766e;
  font-size: 25rpx;
  font-weight: 700;
}
.favorite {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 10rpx 16rpx;
  border-radius: 999rpx;
  background: #f2f4f7;
  color: #667085;
  font-size: 23rpx;
}
.favorite.active {
  background: #fff7ed;
  color: #f97316;
}
.title {
  display: block;
  margin-top: 16rpx;
  color: #101828;
  font-size: 36rpx;
  font-weight: 800;
  line-height: 1.35;
}
.price-row {
  margin-top: 18rpx;
}
.price {
  color: #f97316;
  font-size: 44rpx;
  font-weight: 900;
}
.sales,
.count,
.muted {
  color: #667085;
  font-size: 24rpx;
}
.meta-row {
  justify-content: flex-start;
  margin-top: 12rpx;
  color: #667085;
  font-size: 24rpx;
}
.section-title {
  color: #1f2937;
  font-size: 30rpx;
  font-weight: 800;
}
.description {
  display: block;
  margin-top: 14rpx;
  color: #475467;
  font-size: 28rpx;
  line-height: 1.65;
}
.selected-sku {
  margin-top: 18rpx;
  color: #475467;
  font-size: 26rpx;
}
.selected-price {
  color: #f97316;
  font-weight: 800;
}
.review-list,
.faq-list {
  margin-top: 18rpx;
}
.review-item,
.faq-item {
  padding: 18rpx 0;
  border-top: 1rpx solid #eef2f6;
}
.review-name {
  color: #1f2937;
  font-size: 26rpx;
  font-weight: 700;
}
.review-rating {
  color: #f97316;
  font-size: 24rpx;
}
.review-content,
.answer {
  display: block;
  margin-top: 10rpx;
  color: #475467;
  font-size: 26rpx;
  line-height: 1.55;
}
.question {
  display: block;
  color: #1f2937;
  font-size: 26rpx;
  font-weight: 700;
  line-height: 1.45;
}
.bottom-bar {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 40;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20rpx;
  padding: 20rpx 24rpx calc(20rpx + env(safe-area-inset-bottom));
  background: #ffffff;
  box-shadow: 0 -8rpx 24rpx rgba(16, 24, 40, 0.08);
}
.secondary-button,
.primary-button {
  height: 88rpx;
  border-radius: 999rpx;
  font-size: 29rpx;
  font-weight: 800;
}
.secondary-button {
  border: 2rpx solid #14b8a6;
  background: #ffffff;
  color: #0f766e;
}
.primary-button {
  background: #14b8a6;
  color: #ffffff;
}
</style>

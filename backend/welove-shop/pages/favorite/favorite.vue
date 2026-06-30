<template>
  <view class="page favorite-page">
    <view class="toolbar">
      <view>
        <text class="title">我的收藏</text>
        <text class="subtitle">{{ subtitle }}</text>
      </view>
      <view class="refresh" @tap="loadFavorites">
        <uni-icons type="refreshempty" size="16" color="#14b8a6" />
        <text>刷新</text>
      </view>
    </view>

    <view v-if="loading && !favorites.length" class="state-wrap">
      <uni-load-more status="loading" :contentText="loadText" />
    </view>

    <view v-else-if="errorMessage && !favorites.length" class="state-wrap">
      <EmptyState title="收藏加载失败" :description="errorMessage" />
      <button class="retry" @tap="loadFavorites">重新加载</button>
    </view>

    <view v-else-if="favorites.length" class="list">
      <view v-for="item in favorites" :key="item.id || item.productId" class="favorite-card" @tap="goDetail(item.productId)">
        <image v-if="item.imageUrl && !imageErrorMap[item.productId]" class="cover" :src="item.imageUrl" mode="aspectFill" @error="markImageFailed(item.productId)" />
        <view v-else class="cover placeholder">
          <uni-icons type="image" size="30" color="#98a2b3" />
        </view>
        <view class="info">
          <text class="name">{{ item.productName }}</text>
          <text class="price">{{ item.priceText }}</text>
          <text class="time">收藏时间：{{ item.timeText }}</text>
        </view>
        <view class="remove" @tap.stop="confirmRemove(item)">
          <uni-icons type="trash" size="18" color="#98a2b3" />
        </view>
      </view>
    </view>

    <EmptyState v-else title="暂无收藏" description="看到喜欢的商品，可以点亮收藏按钮。" />
  </view>
</template>

<script>
import EmptyState from '../../components/EmptyState.vue'
import { getFavoriteList, removeFavorite } from '../../api/recommend'
import { requireLogin } from '../../utils/routeGuard'
import { buildImageUrl } from '../../utils/image'
import { formatMoney } from '../../utils/format'

export default {
  components: { EmptyState },
  data() {
    return {
      favorites: [],
      loading: false,
      errorMessage: '',
      imageErrorMap: {},
      loadText: {
        contentdown: '加载更多',
        contentrefresh: '正在加载...',
        contentnomore: '没有更多了'
      }
    }
  },
  computed: {
    subtitle() {
      return this.favorites.length ? `共 ${this.favorites.length} 件商品` : '登录后可同步你收藏的商品'
    }
  },
  onLoad() {
    if (requireLogin('/pages/favorite/favorite')) this.loadFavorites()
  },
  onShow() {
    if (requireLogin('/pages/favorite/favorite')) this.loadFavorites()
  },
  onPullDownRefresh() {
    this.loadFavorites().finally(() => uni.stopPullDownRefresh())
  },
  methods: {
    async loadFavorites() {
      if (this.loading) return
      this.loading = true
      this.errorMessage = ''
      try {
        const data = await getFavoriteList()
        const list = Array.isArray(data) ? data : (data?.records || [])
        this.favorites = list.map(this.normalizeFavorite).filter(item => item.productId)
      } catch (error) {
        this.errorMessage = error?.message || '请确认后端收藏接口已启动。'
      } finally {
        this.loading = false
      }
    },
    normalizeFavorite(item = {}) {
      const product = item.product || {}
      const productId = Number(item.productId || product.id || 0)
      const name = item.productName || product.title || product.name || '商品'
      const rawPrice = item.productPrice ?? product.basePrice ?? product.price ?? 0
      return {
        id: item.id,
        productId,
        productName: name,
        imageUrl: buildImageUrl(item.productImage || product.imageUrl || product.productImage),
        priceText: formatMoney(rawPrice),
        timeText: this.formatTime(item.createTime)
      }
    },
    formatTime(value) {
      if (!value) return '-'
      return String(value).replace('T', ' ').replace(/\.\d+$/, '')
    },
    markImageFailed(productId) {
      this.imageErrorMap = { ...this.imageErrorMap, [productId]: true }
    },
    confirmRemove(item) {
      uni.showModal({
        title: '取消收藏',
        content: `确定从收藏中移除「${item.productName}」吗？`,
        confirmColor: '#f97316',
        success: (res) => {
          if (res.confirm) this.removeItem(item)
        }
      })
    },
    async removeItem(item) {
      const previous = this.favorites
      this.favorites = this.favorites.filter(fav => fav.productId !== item.productId)
      try {
        await removeFavorite(item.productId)
        uni.showToast({ title: '已取消收藏', icon: 'success' })
      } catch (error) {
        this.favorites = previous
        uni.showToast({ title: '操作失败', icon: 'none' })
      }
    },
    goDetail(productId) {
      if (!productId) return
      uni.navigateTo({ url: `/pages/product-detail/product-detail?id=${productId}` })
    }
  }
}
</script>

<style scoped>
.favorite-page {
  min-height: 100vh;
  padding: 24rpx 24rpx 120rpx;
  background: #f6fbfa;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20rpx;
}
.title {
  display: block;
  color: #1f2937;
  font-size: 34rpx;
  font-weight: 900;
}
.subtitle {
  display: block;
  margin-top: 6rpx;
  color: #667085;
  font-size: 24rpx;
}
.refresh {
  display: flex;
  align-items: center;
  gap: 6rpx;
  color: #14b8a6;
  font-size: 26rpx;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}
.favorite-card {
  display: flex;
  align-items: center;
  gap: 18rpx;
  padding: 18rpx;
  border-radius: 18rpx;
  background: #ffffff;
  box-shadow: 0 10rpx 28rpx rgba(15, 118, 110, 0.07);
}
.cover {
  flex: 0 0 auto;
  width: 158rpx;
  height: 158rpx;
  border-radius: 14rpx;
  background: #eef6f5;
}
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
}
.info {
  flex: 1;
  min-width: 0;
}
.name {
  display: -webkit-box;
  overflow: hidden;
  color: #1f2937;
  font-size: 28rpx;
  font-weight: 800;
  line-height: 1.35;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.price {
  display: block;
  margin-top: 10rpx;
  color: #f97316;
  font-size: 32rpx;
  font-weight: 900;
}
.time {
  display: block;
  margin-top: 8rpx;
  color: #98a2b3;
  font-size: 22rpx;
}
.remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 58rpx;
  height: 58rpx;
  border-radius: 50%;
  background: #f2f4f7;
}
.state-wrap {
  padding: 80rpx 0;
}
.retry {
  width: 240rpx;
  height: 72rpx;
  margin: 18rpx auto 0;
  border-radius: 999rpx;
  background: #14b8a6;
  color: #ffffff;
  font-size: 27rpx;
}
</style>

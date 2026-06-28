<template>
  <view class="page product-page">
    <view class="search-panel">
      <uni-search-bar
        v-model="keyword"
        radius="100"
        placeholder="搜索商品、品牌、功效"
        bgColor="#f4f8f8"
        cancelButton="none"
        @confirm="handleSearch"
        @clear="clearSearch"
      />
    </view>

    <scroll-view scroll-x class="category-scroll" show-scrollbar="false">
      <view class="category-row">
        <view class="category-chip" :class="{ active: activeCategoryId === null }" @tap="selectCategory(null)">全部</view>
        <view
          v-for="item in categories"
          :key="item.id"
          class="category-chip"
          :class="{ active: activeCategoryId === item.id }"
          @tap="selectCategory(item.id)"
        >
          {{ item.name || item.categoryName || '分类' }}
        </view>
      </view>
    </scroll-view>

    <view class="sort-bar">
      <view
        v-for="item in sortOptions"
        :key="item.key"
        class="sort-item"
        :class="{ active: sortBy === item.key }"
        @tap="selectSort(item.key)"
      >
        <text>{{ item.label }}</text>
        <text v-if="sortBy === item.key" class="sort-order">{{ sortOrder === 'desc' ? '↓' : '↑' }}</text>
      </view>
    </view>

    <view class="section-head">
      <view>
        <text class="title">{{ listTitle }}</text>
        <text class="subtitle">{{ subtitle }}</text>
      </view>
      <view class="refresh" @tap="refresh">
        <uni-icons type="refreshempty" size="16" color="#14b8a6" />
        <text>刷新</text>
      </view>
    </view>

    <view v-if="loading && !products.length" class="state-wrap">
      <uni-load-more status="loading" :contentText="loadText" />
    </view>

    <view v-else-if="errorMessage && !products.length" class="state-wrap">
      <EmptyState title="商品加载失败" :description="errorMessage" />
      <button class="retry" @tap="refresh">重新加载</button>
    </view>

    <view v-else-if="products.length" class="grid">
      <ProductCard
        v-for="item in products"
        :key="item.id"
        :product="item"
        :favorite="isFavorite(item.id)"
        @click="goDetail(item.id)"
        @favorite="toggleFavorite"
      />
    </view>

    <EmptyState
      v-else
      title="暂无商品"
      :description="emptyDescription"
    />

    <view v-if="products.length" class="load-more">
      <uni-load-more :status="loadMoreStatus" :contentText="loadText" />
    </view>

    <view v-if="showBackTop" class="back-top" @tap="backTop">
      <uni-icons type="up" size="22" color="#ffffff" />
    </view>
  </view>
</template>

<script>
import ProductCard from '../../components/ProductCard.vue'
import EmptyState from '../../components/EmptyState.vue'
import { getProductList, searchProducts } from '../../api/product'
import { getCategories } from '../../api/category'
import { addFavorite, removeFavorite, getFavoriteList } from '../../api/recommend'
import { isLoggedIn } from '../../utils/auth'
import { toLogin } from '../../utils/routeGuard'

export default {
  components: { ProductCard, EmptyState },
  data() {
    return {
      keyword: '',
      categories: [],
      activeCategoryId: null,
      products: [],
      favoriteMap: {},
      sortBy: 'sales',
      sortOrder: 'desc',
      page: 1,
      size: 20,
      hasMore: true,
      loading: false,
      loadingMore: false,
      errorMessage: '',
      showBackTop: false,
      sortOptions: [
        { key: 'sales', label: '销量' },
        { key: 'price', label: '价格' },
        { key: 'rating', label: '评分' },
        { key: 'newest', label: '最新' }
      ],
      loadText: {
        contentdown: '上拉加载更多',
        contentrefresh: '正在加载...',
        contentnomore: '没有更多了'
      }
    }
  },
  computed: {
    listTitle() {
      return this.keyword.trim() ? '搜索结果' : '为你推荐'
    },
    subtitle() {
      if (this.keyword.trim()) return `关键词：${this.keyword.trim()}`
      const current = this.categories.find(item => item.id === this.activeCategoryId)
      return current ? (current.name || current.categoryName || '') : '全部商品'
    },
    emptyDescription() {
      return this.keyword.trim() ? '换个关键词试试，或清空搜索查看全部商品。' : '后端启动并导入数据后，这里会显示商品列表。'
    },
    loadMoreStatus() {
      if (this.loadingMore) return 'loading'
      return this.hasMore ? 'more' : 'noMore'
    }
  },
  onLoad() {
    this.initPage()
  },
  onShow() {
    if (isLoggedIn()) this.loadFavoriteList()
  },
  onPullDownRefresh() {
    this.refresh().finally(() => uni.stopPullDownRefresh())
  },
  onReachBottom() {
    this.loadMore()
  },
  onPageScroll(event) {
    this.showBackTop = event.scrollTop > 480
  },
  methods: {
    async initPage() {
      await Promise.all([this.loadCategories(), this.loadFavoriteList()])
      await this.loadProducts(true)
    },
    async loadCategories() {
      try {
        const data = await getCategories()
        this.categories = Array.isArray(data) ? data : []
      } catch (error) {
        this.categories = []
      }
    },
    async loadFavoriteList() {
      if (!isLoggedIn()) {
        this.favoriteMap = {}
        return
      }
      try {
        const data = await getFavoriteList()
        const list = Array.isArray(data) ? data : (data?.records || [])
        const next = {}
        list.forEach(item => {
          const id = item.productId || item.product?.id || item.id
          if (id) next[id] = true
        })
        this.favoriteMap = next
      } catch (error) {
        this.favoriteMap = {}
      }
    },
    buildQueryParams() {
      return {
        categoryId: this.activeCategoryId || undefined,
        page: this.page,
        size: this.size,
        sortBy: this.sortBy,
        sortOrder: this.sortOrder
      }
    },
    normalizePage(data) {
      if (Array.isArray(data)) {
        return {
          records: data,
          current: this.page,
          pages: data.length >= this.size ? this.page + 1 : this.page,
          total: data.length
        }
      }
      const records = data?.records || data?.list || data?.items || []
      const current = Number(data?.current || data?.page || this.page)
      const total = Number(data?.total || records.length || 0)
      const pages = Number(data?.pages || data?.totalPages || (total ? Math.ceil(total / this.size) : current))
      return { records, current, pages, total }
    },
    async loadProducts(reset = false) {
      if (this.loading || this.loadingMore) return
      if (reset) {
        this.page = 1
        this.hasMore = true
        this.loading = true
      } else {
        if (!this.hasMore || this.keyword.trim()) return
        this.loadingMore = true
      }

      try {
        this.errorMessage = ''
        const word = this.keyword.trim()
        if (word) {
          const data = await searchProducts({ keyword: word, limit: this.size })
          this.products = Array.isArray(data) ? data : []
          this.hasMore = false
          return
        }

        const data = await getProductList(this.buildQueryParams())
        const pageData = this.normalizePage(data)
        const records = pageData.records || []
        this.products = reset ? records : this.products.concat(records)
        this.page = pageData.current + 1
        this.hasMore = records.length > 0 && pageData.current < pageData.pages
      } catch (error) {
        uni.showToast({ title: '商品加载失败', icon: 'none' })
      } finally {
        this.loading = false
        this.loadingMore = false
      }
    },
    async refresh() {
      this.errorMessage = ''
      await this.loadCategories()
      await this.loadFavoriteList()
      await this.loadProducts(true)
    },
    loadMore() {
      this.loadProducts(false)
    },
    handleSearch() {
      this.loadProducts(true)
    },
    clearSearch() {
      this.keyword = ''
      this.loadProducts(true)
    },
    selectCategory(categoryId) {
      if (this.activeCategoryId === categoryId) return
      this.activeCategoryId = categoryId
      this.loadProducts(true)
      this.backTop()
    },
    selectSort(sortBy) {
      this.sortOrder = this.sortBy === sortBy && this.sortOrder === 'desc' ? 'asc' : 'desc'
      this.sortBy = sortBy
      this.loadProducts(true)
      this.backTop()
    },
    isFavorite(productId) {
      return Boolean(this.favoriteMap[productId])
    },
    async toggleFavorite(product) {
      const productId = product?.id
      if (!productId) return
      if (!isLoggedIn()) {
        toLogin('/pages/product-list/product-list')
        return
      }

      const wasFavorite = this.isFavorite(productId)
      this.favoriteMap = { ...this.favoriteMap, [productId]: !wasFavorite }
      if (wasFavorite) delete this.favoriteMap[productId]

      try {
        if (wasFavorite) await removeFavorite(productId)
        else await addFavorite(productId)
        await this.loadFavoriteList()
      } catch (error) {
        this.favoriteMap = { ...this.favoriteMap, [productId]: wasFavorite }
        if (!wasFavorite) delete this.favoriteMap[productId]
        uni.showToast({ title: '收藏操作失败', icon: 'none' })
      }
    },
    goDetail(id) {
      if (!id) return
      uni.navigateTo({ url: `/pages/product-detail/product-detail?id=${id}` })
    },
    backTop() {
      uni.pageScrollTo({ scrollTop: 0, duration: 180 })
    }
  }
}
</script>

<style scoped>
.product-page {
  min-height: 100vh;
  padding: 18rpx 24rpx 140rpx;
  background: #f6fbfa;
}
.search-panel {
  border-radius: 999rpx;
  background: #ffffff;
  box-shadow: 0 10rpx 30rpx rgba(15, 118, 110, 0.07);
}
.category-scroll {
  width: 100%;
  margin-top: 18rpx;
  white-space: nowrap;
}
.category-row {
  display: flex;
  gap: 16rpx;
  padding: 4rpx 0 18rpx;
}
.category-chip {
  flex: 0 0 auto;
  padding: 14rpx 24rpx;
  border: 1rpx solid #d7e7e4;
  border-radius: 999rpx;
  background: #ffffff;
  color: #475467;
  font-size: 24rpx;
}
.category-chip.active {
  border-color: #14b8a6;
  background: #14b8a6;
  color: #ffffff;
  font-weight: 700;
}
.sort-bar {
  display: flex;
  align-items: center;
  gap: 26rpx;
  padding: 12rpx 4rpx 22rpx;
}
.sort-item {
  display: flex;
  align-items: center;
  gap: 4rpx;
  color: #667085;
  font-size: 25rpx;
}
.sort-item.active {
  color: #0f766e;
  font-weight: 800;
}
.sort-order {
  font-size: 22rpx;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18rpx;
}
.title {
  display: block;
  color: #1f2937;
  font-size: 32rpx;
  font-weight: 800;
}
.subtitle {
  display: block;
  margin-top: 5rpx;
  color: #667085;
  font-size: 23rpx;
}
.refresh {
  display: flex;
  align-items: center;
  gap: 6rpx;
  color: #14b8a6;
  font-size: 26rpx;
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20rpx;
}
.state-wrap,
.load-more {
  padding: 30rpx 0;
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
.back-top {
  position: fixed;
  right: 28rpx;
  bottom: 150rpx;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 78rpx;
  height: 78rpx;
  border-radius: 50%;
  background: #14b8a6;
  box-shadow: 0 12rpx 28rpx rgba(20, 184, 166, 0.28);
}
</style>

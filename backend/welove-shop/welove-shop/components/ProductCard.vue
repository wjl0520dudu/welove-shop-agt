<template>
  <view class="product-card" @tap="$emit('click')">
    <view class="image-wrap">
      <image v-if="imageUrl && !imageFailed" class="image" :src="imageUrl" mode="aspectFill" @error="imageFailed = true" />
      <view v-else class="image placeholder">
        <uni-icons type="image" size="28" color="#98a2b3" />
      </view>
      <view class="tag">精选</view>
      <view class="favorite" :class="{ active: favorite }" @tap.stop="$emit('favorite', product)">
        <uni-icons type="heart-filled" size="18" :color="favorite ? '#f97316' : '#ffffff'" />
      </view>
    </view>
    <view class="content">
      <text class="name">{{ title }}</text>
      <view class="meta-row">
        <text class="brand">{{ product.brand || product.subCategory || product.categoryName || '好物' }}</text>
        <text class="rating">{{ rating }} 分</text>
      </view>
      <view class="row">
        <text class="price">¥{{ price }}</text>
        <text class="sales">{{ product.salesCount || product.sales || 0 }} 人买过</text>
      </view>
    </view>
  </view>
</template>

<script>
import { formatMoney } from '../utils/format'
import { buildImageUrl, pickProductImage } from '../utils/image'

export default {
  name: 'ProductCard',
  props: {
    product: { type: Object, default: () => ({}) },
    favorite: { type: Boolean, default: false }
  },
  emits: ['click', 'favorite'],
  data() {
    return { imageFailed: false }
  },
  watch: {
    product() { this.imageFailed = false }
  },
  computed: {
    imageUrl() {
      return buildImageUrl(pickProductImage(this.product))
    },
    title() {
      return this.product.title || this.product.name || '未命名商品'
    },
    price() {
      return formatMoney(this.product.basePrice || this.product.price || 0)
    },
    rating() {
      return Number(this.product.rating || 0).toFixed(1)
    }
  }
}
</script>

<style scoped>
.product-card {
  overflow: hidden;
  border-radius: 22rpx;
  background: #ffffff;
  box-shadow: 0 12rpx 30rpx rgba(15, 118, 110, 0.08);
}
.image-wrap {
  position: relative;
}
.image {
  width: 100%;
  height: 320rpx;
  background: #eef6f5;
}
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
}
.tag {
  position: absolute;
  left: 14rpx;
  top: 14rpx;
  padding: 7rpx 14rpx;
  border-radius: 999rpx;
  background: rgba(255, 247, 237, 0.96);
  color: #f97316;
  font-size: 20rpx;
  font-weight: 700;
}
.favorite {
  position: absolute;
  right: 14rpx;
  top: 14rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 58rpx;
  height: 58rpx;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.42);
}
.favorite.active {
  background: rgba(255, 247, 237, 0.96);
}
.content {
  padding: 18rpx;
}
.name {
  display: -webkit-box;
  overflow: hidden;
  min-height: 76rpx;
  color: #1f2937;
  font-size: 28rpx;
  font-weight: 700;
  line-height: 1.35;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10rpx;
}
.brand,
.rating {
  overflow: hidden;
  color: #667085;
  font-size: 22rpx;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.brand { max-width: 180rpx; }
.row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-top: 14rpx;
}
.price {
  color: #f97316;
  font-size: 31rpx;
  font-weight: 800;
}
.sales {
  color: #98a2b3;
  font-size: 21rpx;
}
</style>

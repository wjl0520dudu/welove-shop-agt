<template>
  <view class="product-card" @tap="$emit('click')">
    <view class="image-wrap">
      <image v-if="product.imageUrl" class="image" :src="product.imageUrl" mode="aspectFill" />
      <view v-else class="image placeholder">
        <uni-icons type="image" size="28" color="#98a2b3" />
      </view>
      <view class="tag">精选</view>
    </view>
    <view class="content">
      <text class="name">{{ product.title || '未命名商品' }}</text>
      <view class="meta-row">
        <text class="brand">{{ product.brand || product.subCategory || '好物' }}</text>
        <text class="rating">{{ product.rating || 0 }} 分</text>
      </view>
      <view class="row">
        <text class="price">¥{{ Number(product.basePrice || 0).toFixed(2) }}</text>
        <text class="sales">{{ product.salesCount || 0 }} 人买过</text>
      </view>
    </view>
  </view>
</template>

<script>
export default {
  name: 'ProductCard',
  props: {
    product: { type: Object, default: () => ({}) }
  },
  emits: ['click']
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
  color: #667085;
  font-size: 22rpx;
}
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

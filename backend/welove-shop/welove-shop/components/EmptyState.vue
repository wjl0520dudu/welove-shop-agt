<template>
  <view class="empty">
    <text class="empty-title">{{ title }}</text>
    <text v-if="description" class="empty-desc">{{ description }}</text>
  </view>
</template>

<script>
export default {
  name: 'EmptyState',
  props: {
    title: { type: String, default: '暂无数据' },
    description: { type: String, default: '' }
  }
}
</script>

<style scoped>
.empty {
  padding: 80rpx 32rpx;
  text-align: center;
}
.empty-title {
  display: block;
  font-size: 30rpx;
  color: #344054;
}
.empty-desc {
  display: block;
  margin-top: 12rpx;
  font-size: 26rpx;
  color: #98a2b3;
}
</style>

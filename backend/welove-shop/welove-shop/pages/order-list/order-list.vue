<template>
  <view class="page order-page">
    <scroll-view scroll-x class="status-tabs">
      <view v-for="tab in tabs" :key="tab.key" class="tab" :class="{ active: selectedStatus === tab.value }" @tap="selectStatus(tab.value)">{{ tab.text }}</view>
    </scroll-view>
    <view v-if="loading && !orders.length" class="loading-wrap"><uni-load-more status="loading" :contentText="loadText" /></view>
    <EmptyState v-else-if="!orders.length" title="暂无订单" description="下单后可在这里查看订单进度。" />
    <scroll-view v-else scroll-y class="order-scroll" @scrolltolower="loadMore">
      <view v-for="order in orders" :key="order.id" class="order-card" @tap="goDetail(order)">
        <view class="order-head"><text class="order-no">订单号: {{ order.orderNo || order.id }}</text><text class="status" :class="`status-${order.status}`">{{ statusText(order.status) }}</text></view>
        <view v-for="item in visibleItems(order)" :key="item.id || item.productId" class="goods-row">
          <view class="thumb"><image v-if="itemImage(item)" :src="itemImage(item)" mode="aspectFill" /><uni-icons v-else type="image" size="22" color="#98a2b3" /></view>
          <view class="goods-info"><text class="goods-title">{{ item.productTitle || '订单商品' }}</text><text v-if="item.skuProperties" class="sku-text">{{ item.skuProperties }}</text></view>
          <text class="quantity">x{{ item.quantity || 1 }}</text>
        </view>
        <text v-if="(order.items || []).length > 3" class="more-count">共 {{ order.items.length }} 件商品</text>
        <view class="order-foot"><text class="time">{{ dateText(order.createTime) }}</text><view class="amount-row"><text>合计</text><text class="amount">{{ formatMoney(order.payAmount || order.totalAmount || 0) }}</text></view></view>
      </view>
      <uni-load-more v-if="orders.length" :status="hasMore ? (loadingMore ? 'loading' : 'more') : 'noMore'" />
    </scroll-view>
  </view>
</template>
<script>
import EmptyState from '../../components/EmptyState.vue'
import { getOrderList } from '../../api/order'
import { formatMoney, orderStatusText } from '../../utils/format'
import { buildImageUrl } from '../../utils/image'
import { requireLogin } from '../../utils/routeGuard'
export default { components:{EmptyState}, data(){ return { tabs:[{text:'全部',value:null,key:'all'},{text:'待付款',value:0,key:'0'},{text:'待发货',value:1,key:'1'},{text:'待收货',value:2,key:'2'},{text:'已完成',value:3,key:'3'},{text:'已取消',value:4,key:'4'}], selectedStatus:null, orders:[], page:1, size:10, total:0, loading:false, loadingMore:false, loadText:{contentdown:'加载更多',contentrefresh:'正在加载...',contentnomore:'没有更多了'} } }, computed:{ hasMore(){ return this.orders.length < this.total } }, onLoad(query={}){ if(!requireLogin('/pages/order-list/order-list')) return; if(query.status !== undefined && query.status !== '') this.selectedStatus = Number(query.status) }, onShow(){ if(!requireLogin('/pages/order-list/order-list')) return; this.refresh() }, onPullDownRefresh(){ this.refresh().finally(()=>uni.stopPullDownRefresh()) }, methods:{ formatMoney(value){return formatMoney(value)}, statusText(status){return orderStatusText(status)}, dateText(value){return value ? String(value).replace('T',' ').slice(0,16) : ''}, visibleItems(order){return (order.items || []).slice(0,3)}, itemImage(item){return buildImageUrl(item.productImage || item.imageUrl || '')}, async refresh(){ this.page=1; this.loading=true; try{ const data=await this.fetchOrders(this.page); this.orders=data.records; this.total=data.total } catch(e){ uni.showToast({title:'订单加载失败',icon:'none'}) } finally{ this.loading=false } }, async loadMore(){ if(!this.hasMore || this.loadingMore) return; this.loadingMore=true; try{ const next=this.page+1; const data=await this.fetchOrders(next); this.page=next; this.orders=this.orders.concat(data.records); this.total=data.total } finally{ this.loadingMore=false } }, async fetchOrders(page){ const params={page,size:this.size}; if(this.selectedStatus !== null && this.selectedStatus !== undefined) params.status=this.selectedStatus; const data=await getOrderList(params); const records=Array.isArray(data)?data:(data?.records || data?.items || data?.list || []); return {records,total:Number(data?.total || records.length)} }, selectStatus(status){ this.selectedStatus=status; this.refresh() }, goDetail(order){ uni.navigateTo({url:`/pages/order-detail/order-detail?id=${order.id}`}) } } }
</script>
<style scoped>
.order-page{min-height:100vh;padding:0 22rpx 40rpx}.status-tabs{white-space:nowrap;margin:0 -22rpx 18rpx;padding:18rpx 22rpx;background:#fff}.tab{display:inline-flex;align-items:center;justify-content:center;height:62rpx;margin-right:14rpx;padding:0 24rpx;border-radius:999rpx;background:#f2f4f7;color:#667085;font-size:26rpx;font-weight:800}.tab.active{background:#14b8a6;color:#fff}.loading-wrap{padding:120rpx 0}.order-scroll{height:calc(100vh - 104rpx)}.order-card{margin-bottom:18rpx;padding:24rpx;border-radius:22rpx;background:#fff;box-shadow:0 10rpx 28rpx rgba(15,118,110,.06)}.order-head{display:flex;align-items:center;justify-content:space-between;gap:16rpx;margin-bottom:16rpx}.order-no{flex:1;color:#667085;font-size:24rpx;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.status{font-size:25rpx;font-weight:900}.status-0{color:#ef4444}.status-1{color:#f97316}.status-2{color:#14b8a6}.status-3{color:#2563eb}.status-4{color:#98a2b3}.goods-row{display:flex;align-items:center;gap:16rpx;padding:10rpx 0}.thumb{display:flex;align-items:center;justify-content:center;width:104rpx;height:104rpx;border-radius:14rpx;background:#f4f8f8;overflow:hidden}.thumb image{width:100%;height:100%}.goods-info{flex:1;min-width:0}.goods-title{display:block;color:#1f2937;font-size:27rpx;font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sku-text{display:block;margin-top:6rpx;color:#667085;font-size:22rpx;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.quantity{color:#667085;font-size:24rpx;font-weight:700}.more-count{display:block;margin-top:8rpx;color:#98a2b3;font-size:23rpx;text-align:right}.order-foot{display:flex;align-items:center;justify-content:space-between;margin-top:16rpx;padding-top:16rpx;border-top:1rpx solid #eef2f7}.time{color:#98a2b3;font-size:23rpx}.amount-row{display:flex;align-items:baseline;gap:8rpx;color:#344054;font-size:25rpx}.amount{color:#f97316;font-size:31rpx;font-weight:900}
</style>

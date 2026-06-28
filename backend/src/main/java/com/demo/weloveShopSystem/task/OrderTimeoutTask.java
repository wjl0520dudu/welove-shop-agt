package com.demo.weloveShopSystem.task;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;

import com.demo.weloveShopSystem.entity.Order;
import com.demo.weloveShopSystem.entity.OrderItem;
import com.demo.weloveShopSystem.mapper.OrderItemMapper;
import com.demo.weloveShopSystem.mapper.OrderMapper;
import com.demo.weloveShopSystem.mapper.ProductSkuMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 订单超时取消定时任务。
 * 定期扫描未支付且超过支付时限的订单，恢复库存并将订单状态改为已取消。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class OrderTimeoutTask {

    /** 订单 Mapper。 */
    private final OrderMapper orderMapper;
    /** 订单明细 Mapper。 */
    private final OrderItemMapper orderItemMapper;
    /** 商品 SKU Mapper，用于恢复库存。 */
    private final ProductSkuMapper productSkuMapper;

    /** 待支付订单超时时间，单位分钟。 */
    private static final int PAY_TIMEOUT_MINUTES = 10;

    /**
     * 每分钟扫描一次超时未支付订单。
     */
    @Scheduled(fixedRate = 60000)
    @Transactional
    public void cancelExpiredOrders() {
        LocalDateTime deadline = LocalDateTime.now().minusMinutes(PAY_TIMEOUT_MINUTES);

        // 查询超时的待付款订单。
        List<Order> expiredOrders = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getStatus, 0)
                        .le(Order::getCreateTime, deadline)
                        .select(Order::getId));

        if (expiredOrders.isEmpty()) return;

        List<Long> orderIds = expiredOrders.stream().map(Order::getId).toList();

        // 恢复对应 SKU 库存。
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>().in(OrderItem::getOrderId, orderIds));
        for (OrderItem item : items) {
            if (item.getSkuId() != null) {
                productSkuMapper.updateStock(item.getSkuId(), item.getQuantity());
            }
        }

        // 批量取消仍处于待付款状态的订单。
        int count = orderMapper.update(null,
                new LambdaUpdateWrapper<Order>()
                        .in(Order::getId, orderIds)
                        .eq(Order::getStatus, 0)
                        .set(Order::getStatus, 4)
                        .set(Order::getUpdateTime, LocalDateTime.now()));
        if (count > 0) {
            log.info("自动取消超时未支付订单 {} 个", count);
        }
    }
}

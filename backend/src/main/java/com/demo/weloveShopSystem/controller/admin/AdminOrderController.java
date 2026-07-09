package com.demo.weloveShopSystem.controller.admin;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Order;
import com.demo.weloveShopSystem.entity.OrderItem;
import com.demo.weloveShopSystem.mapper.OrderItemMapper;
import com.demo.weloveShopSystem.mapper.OrderMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 后台订单管理控制器。
 * <p>
 * 覆盖订单分页搜索、订单明细查看、订单状态维度的统计概览。
 * status 枚举语义:0=待支付 1=待发货 2=待收货 3=已完成 4=已取消(与订单主表约定一致)。
 */
@RestController
@RequestMapping("/api/admin/order")
@RequiredArgsConstructor
public class AdminOrderController {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;

    /**
     * 分页查询订单列表。
     * keyword 用于收货人姓名和手机号的联合模糊匹配,orderNo 单独精确检索。
     */
    @GetMapping("/list")
    public Result<IPage<Order>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) Long userId,
            @RequestParam(required = false) Integer status,
            @RequestParam(required = false) String orderNo,
            @RequestParam(required = false) String keyword) {
        QueryWrapper<Order> qw = new QueryWrapper<>();
        if (userId != null) {
            qw.eq("user_id", userId);
        }
        if (status != null) {
            qw.eq("status", status);
        }
        if (orderNo != null && !orderNo.isEmpty()) {
            qw.like("order_no", orderNo);
        }
        if (keyword != null && !keyword.isEmpty()) {
            qw.and(w -> w.like("receiver_name", keyword).or().like("receiver_phone", keyword));
        }
        qw.orderByDesc("create_time");
        return Result.success(orderMapper.selectPage(new Page<>(page, size), qw));
    }

    /** 查询指定订单的商品明细。 */
    @GetMapping("/{id}/items")
    public Result<List<OrderItem>> items(@PathVariable Long id) {
        return Result.success(orderItemMapper.selectList(
                new QueryWrapper<OrderItem>().eq("order_id", id)));
    }

    /**
     * 订单状态分布 + 今日新增 + 已完成订单的累计营收。
     * 累计营收对已完成订单一次性拉出并 sum,数据量大时可改为直接走 SQL sum。
     */
    @GetMapping("/stats")
    public Result<Map<String, Object>> stats() {
        Map<String, Object> stats = new HashMap<>();
        stats.put("totalOrders", orderMapper.selectCount(null));
        stats.put("pendingPayment", orderMapper.selectCount(new QueryWrapper<Order>().eq("status", 0)));
        stats.put("pendingDelivery", orderMapper.selectCount(new QueryWrapper<Order>().eq("status", 1)));
        stats.put("delivered", orderMapper.selectCount(new QueryWrapper<Order>().eq("status", 2)));
        stats.put("completed", orderMapper.selectCount(new QueryWrapper<Order>().eq("status", 3)));
        stats.put("cancelled", orderMapper.selectCount(new QueryWrapper<Order>().eq("status", 4)));

        stats.put("todayOrders", orderMapper.selectCount(new QueryWrapper<Order>()
                .ge("create_time", LocalDate.now().atStartOfDay())));

        stats.put("totalRevenue", orderMapper.selectList(new QueryWrapper<Order>().eq("status", 3))
                .stream()
                .mapToDouble(o -> o.getPayAmount() != null ? o.getPayAmount().doubleValue() : 0)
                .sum());
        return Result.success(stats);
    }
}

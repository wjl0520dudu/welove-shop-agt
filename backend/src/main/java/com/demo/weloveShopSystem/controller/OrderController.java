package com.demo.weloveShopSystem.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;

import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.dto.CreateOrderRequest;
import com.demo.weloveShopSystem.service.OrderService;
import com.demo.weloveShopSystem.vo.OrderVO;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

/**
 * 用户订单控制器。
 */
@RestController
@RequestMapping("/api/order")
@RequiredArgsConstructor
public class OrderController {

    private final OrderService orderService;

    /** 从 Spring Security 上下文获取当前登录用户 ID。 */
    private Long getCurrentUserId() {
        return Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
    }

    /** 创建订单。 */
    @PostMapping("/create")
    public Result<OrderVO> createOrder(@RequestBody CreateOrderRequest request) {
        try {
            return Result.success(orderService.createOrder(getCurrentUserId(), request));
        } catch (RuntimeException e) {
            return Result.error(e.getMessage());
        }
    }

    /** 分页查询当前用户订单列表。 */
    @GetMapping("/list")
    public Result<IPage<OrderVO>> listOrders(
            @RequestParam(required = false) Integer status,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size) {
        return Result.success(orderService.listOrders(getCurrentUserId(), status, page, size));
    }

    /** 查询当前用户订单详情。 */
    @GetMapping("/{id}")
    public Result<OrderVO> getOrderDetail(@PathVariable Long id) {
        try {
            return Result.success(orderService.getOrderDetail(getCurrentUserId(), id));
        } catch (RuntimeException e) {
            return Result.error(e.getMessage());
        }
    }

    /** 支付订单。 */
    @PutMapping("/{id}/pay")
    public Result<OrderVO> payOrder(@PathVariable Long id) {
        try {
            return Result.success(orderService.payOrder(getCurrentUserId(), id));
        } catch (RuntimeException e) {
            return Result.error(e.getMessage());
        }
    }

    /** 取消订单。 */
    @PutMapping("/{id}/cancel")
    public Result<OrderVO> cancelOrder(@PathVariable Long id) {
        try {
            return Result.success(orderService.cancelOrder(getCurrentUserId(), id));
        } catch (RuntimeException e) {
            return Result.error(e.getMessage());
        }
    }

    /** 确认收货。 */
    @PutMapping("/{id}/receive")
    public Result<OrderVO> confirmReceive(@PathVariable Long id) {
        try {
            return Result.success(orderService.confirmReceive(getCurrentUserId(), id));
        } catch (RuntimeException e) {
            return Result.error(e.getMessage());
        }
    }

    /** 删除订单。 */
    @DeleteMapping("/{id}")
    public Result<String> deleteOrder(@PathVariable Long id) {
        try {
            orderService.deleteOrder(getCurrentUserId(), id);
            return Result.success("订单已删除");
        } catch (RuntimeException e) {
            return Result.error(e.getMessage());
        }
    }
}

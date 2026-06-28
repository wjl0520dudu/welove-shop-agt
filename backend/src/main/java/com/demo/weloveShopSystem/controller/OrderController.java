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

}

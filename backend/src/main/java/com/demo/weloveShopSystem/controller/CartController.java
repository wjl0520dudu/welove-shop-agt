package com.demo.weloveShopSystem.controller;


import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Cart;
import com.demo.weloveShopSystem.service.CartService;
import com.demo.weloveShopSystem.vo.CartItemVO;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 用户购物车控制器。
 */
@RestController
@RequestMapping("/api/cart")
@RequiredArgsConstructor
public class CartController {

    private final CartService cartService;

    /** 从 Spring Security 上下文获取当前登录用户 ID。 */
    private Long getCurrentUserId() {
        return Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
    }

    /** 添加商品到购物车，默认数量为 1。 */
    @PostMapping("/add")
    public Result<Cart> add(@RequestParam Long productId,
                            @RequestParam(required = false) Long skuId) {
        return Result.success(cartService.addItem(getCurrentUserId(), productId, skuId, 1));
    }

    /** 移除购物车商品；传入 quantity 时按数量递减。 */
    @DeleteMapping("/remove")
    public Result<Void> remove(@RequestParam Long productId,
                               @RequestParam(required = false) Integer quantity) {
        Long userId = getCurrentUserId();
        if (quantity != null && quantity > 0) {
            cartService.decreaseQuantity(userId, productId, quantity);
        } else {
            cartService.removeItem(userId, productId);
        }
        return Result.success(null);
    }

    /** 按购物车条目 ID 删除商品。 */
    @DeleteMapping("/removeById")
    public Result<Void> removeById(@RequestParam Long cartItemId) {
        cartService.removeByCartItemId(getCurrentUserId(), cartItemId);
        return Result.success(null);
    }

    /** 更新购物车商品数量。 */
    @PutMapping("/update")
    public Result<Cart> update(
            @RequestParam Long productId,
            @RequestParam Integer quantity) {
        Long userId = getCurrentUserId();
        cartService.updateQuantity(userId, productId, quantity);
        return Result.success(cartService.getByUserIdAndProductId(userId, productId));
    }

    /** 更新购物车商品规格。 */
    @PutMapping("/updateSku")
    public Result<Void> updateSku(
            @RequestParam Long productId,
            @RequestParam Long oldSkuId,
            @RequestParam Long newSkuId) {
        cartService.updateSku(getCurrentUserId(), productId, oldSkuId, newSkuId);
        return Result.success(null);
    }

    /** 查询当前用户购物车列表。 */
    @GetMapping("/list")
    public Result<List<CartItemVO>> list() {
        return Result.success(cartService.listWithProductByUserId(getCurrentUserId()));
    }

    /** 查询当前用户购物车条目数量。 */
    @GetMapping("/count")
    public Result<Integer> count() {
        return Result.success(cartService.getCount(getCurrentUserId()));
    }

    /** 全选或取消全选购物车商品。 */
    @PostMapping("/checkAll")
    public Result<Void> checkAll(@RequestParam boolean checked) {
        cartService.checkAll(getCurrentUserId(), checked);
        return Result.success(null);
    }
}

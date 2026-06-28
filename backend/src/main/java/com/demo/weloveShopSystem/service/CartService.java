package com.demo.weloveShopSystem.service;


import com.demo.weloveShopSystem.entity.Cart;
import com.demo.weloveShopSystem.vo.CartItemVO;

import java.util.List;

/**
 * 购物车服务接口。
 */
public interface CartService {
    /** 添加商品到购物车。 */
    Cart addItem(Long userId, Long productId, Long skuId, Integer quantity);
    /** 移除用户购物车中的某个商品。 */
    void removeItem(Long userId, Long productId);
    /** 按购物车记录 ID 移除商品。 */
    void removeByCartItemId(Long userId, Long cartItemId);
    /** 减少购物车商品数量。 */
    void decreaseQuantity(Long userId, Long productId, Integer quantity);
    /** 更新购物车商品数量。 */
    void updateQuantity(Long userId, Long productId, Integer quantity);
    /** 更新购物车商品规格。 */
    void updateSku(Long userId, Long productId, Long oldSkuId, Long newSkuId);
    /** 查询用户购物车原始记录。 */
    List<Cart> listByUserId(Long userId);
    /** 查询带商品和 SKU 信息的购物车列表。 */
    List<CartItemVO> listWithProductByUserId(Long userId);
    /** 查询用户购物车中的某个商品记录。 */
    Cart getByUserIdAndProductId(Long userId, Long productId);
    /** 查询用户购物车条目数量。 */
    int getCount(Long userId);
    /** 全选或取消全选购物车商品。 */
    void checkAll(Long userId, boolean checked);
}

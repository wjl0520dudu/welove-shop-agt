package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.entity.UserFavorite;

import java.util.List;

/**
 * 用户收藏服务接口。
 */
public interface UserFavoriteService {
    /** 添加商品收藏。 */
    void addFavorite(Long userId, Long productId);
    /** 取消商品收藏。 */
    void removeFavorite(Long userId, Long productId);
    /** 查询用户收藏列表。 */
    List<UserFavorite> listByUserId(Long userId);
}

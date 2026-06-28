package com.demo.weloveShopSystem.service;


import com.demo.weloveShopSystem.entity.ProductReview;

import java.util.List;

/**
 * 商品评价服务接口。
 */
public interface ProductReviewService {
    /** 查询指定商品的评价列表。 */
    List<ProductReview> listByProductId(Long productId, int limit);
    /** 提交商品评价。 */
    ProductReview submitReview(Long userId, Long productId, Integer rating, String content);
}

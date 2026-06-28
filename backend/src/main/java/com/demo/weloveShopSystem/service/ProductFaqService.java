package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.entity.ProductFaq;

import java.util.List;

/**
 * 商品 FAQ 服务接口。
 */
public interface ProductFaqService {
    /** 查询指定商品的常见问答列表。 */
    List<ProductFaq> listByProductId(Long productId);
}

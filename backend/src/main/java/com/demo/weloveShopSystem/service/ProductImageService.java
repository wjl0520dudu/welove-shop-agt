package com.demo.weloveShopSystem.service;


import com.demo.weloveShopSystem.entity.ProductImage;

import java.util.List;

/**
 * 商品图片服务接口。
 */
public interface ProductImageService {
    /** 查询指定商品的图片列表。 */
    List<ProductImage> listByProductId(Long productId);
}

package com.demo.weloveShopSystem.service;


import com.demo.weloveShopSystem.entity.ProductSku;

import java.util.List;

/**
 * 商品 SKU 服务接口。
 */
public interface ProductSkuService {
    /** 查询指定商品的规格列表。 */
    List<ProductSku> listByProductId(Long productId);
}

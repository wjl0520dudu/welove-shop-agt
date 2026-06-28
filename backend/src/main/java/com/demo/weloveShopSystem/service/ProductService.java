package com.demo.weloveShopSystem.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.demo.weloveShopSystem.entity.Product;
import java.util.List;

/**
 * 商品服务接口。
 */
public interface ProductService {
    /** 按分类分页查询商品，可指定排序字段和排序方向。 */
    IPage<Product> listByCategory(Long categoryId, int page, int size, String sortBy, String sortOrder);
    /** 根据商品 ID 查询商品详情。 */
    Product getById(Long id);
    /** 根据关键词搜索商品。 */
    List<Product> search(String keyword, int limit);
    /** 查询热门商品，当前按销量倒序排序。 */
    List<Product> getHotProducts(int limit);
}

package com.demo.weloveShopSystem.controller;

import com.demo.weloveShopSystem.entity.Category;

import java.util.List;

/**
 * 商品分类服务接口。
 */
public interface CategoryService {
    /** 查询启用状态的分类列表。 */
    List<Category> listActive();
    /** 根据分类 ID 查询分类详情。 */
    Category getById(Long id);
}

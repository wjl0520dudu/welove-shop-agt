package com.demo.weloveShopSystem.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Product;
import com.demo.weloveShopSystem.service.ProductService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 商品查询、搜索、评价和详情控制器。
 */
@RestController
@RequestMapping("/api/product")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    /** 分页查询商品列表，可按分类和排序字段筛选。 */
    @GetMapping("/list")
    public Result<IPage<Product>> list(
            @RequestParam(required = false) Long categoryId,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String sortBy,
            @RequestParam(defaultValue = "desc") String sortOrder) {
        return Result.success(productService.listByCategory(categoryId, page, size, sortBy, sortOrder));
    }


    /** 按关键词搜索商品。 */
    @GetMapping("/search")
    public Result<List<Product>> search(
            @RequestParam String keyword,
            @RequestParam(defaultValue = "10") int limit) {
        return Result.success(productService.search(keyword, limit));
    }

    /** 查询热门商品，当前按销量排序。 */
    @GetMapping("/hot")
    public Result<List<Product>> hot(@RequestParam(defaultValue = "10") int limit) {
        return Result.success(productService.getHotProducts(limit));
    }
}

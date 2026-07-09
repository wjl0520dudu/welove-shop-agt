package com.demo.weloveShopSystem.controller;


import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Category;
import com.demo.weloveShopSystem.service.CategoryService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 商品分类控制器。
 */
@RestController
@RequestMapping("/api/category")
@RequiredArgsConstructor
public class CategoryController {

    private final CategoryService categoryService;

    /** 查询启用状态的分类列表。 */
    @GetMapping("/list")
    public Result<List<Category>> list() {
        return Result.success(categoryService.listActive());
    }

}

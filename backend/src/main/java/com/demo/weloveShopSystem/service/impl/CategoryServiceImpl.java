package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import com.demo.weloveShopSystem.entity.Category;
import com.demo.weloveShopSystem.mapper.CategoryMapper;
import com.demo.weloveShopSystem.service.CategoryService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class CategoryServiceImpl implements CategoryService {

    private final CategoryMapper categoryMapper;

    @Override
    public List<Category> listActive() {
        return categoryMapper.selectList(
                new LambdaQueryWrapper<Category>()
                        .eq(Category::getIsActive, true)
                        .orderByAsc(Category::getSortOrder));
    }

    @Override
    public Category getById(Long id) {
        return categoryMapper.selectById(id);
    }
}

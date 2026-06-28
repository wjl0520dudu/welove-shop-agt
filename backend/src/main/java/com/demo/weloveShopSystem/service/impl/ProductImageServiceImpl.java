package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import com.demo.weloveShopSystem.entity.ProductImage;
import com.demo.weloveShopSystem.mapper.ProductImageMapper;
import com.demo.weloveShopSystem.service.ProductImageService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class ProductImageServiceImpl implements ProductImageService {

    private final ProductImageMapper productImageMapper;

    @Override
    public List<ProductImage> listByProductId(Long productId) {
        return productImageMapper.selectList(
                new LambdaQueryWrapper<ProductImage>()
                        .eq(ProductImage::getProductId, productId)
                        .orderByAsc(ProductImage::getSortOrder));
    }
}

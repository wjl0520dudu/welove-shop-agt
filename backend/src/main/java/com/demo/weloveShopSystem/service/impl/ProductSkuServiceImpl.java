package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import com.demo.weloveShopSystem.entity.ProductSku;
import com.demo.weloveShopSystem.mapper.ProductSkuMapper;
import com.demo.weloveShopSystem.service.ProductSkuService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class ProductSkuServiceImpl implements ProductSkuService {

    private final ProductSkuMapper productSkuMapper;

    @Override
    public List<ProductSku> listByProductId(Long productId) {
        return productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, productId)
                        .orderByDesc(ProductSku::getIsDefault));
    }
}

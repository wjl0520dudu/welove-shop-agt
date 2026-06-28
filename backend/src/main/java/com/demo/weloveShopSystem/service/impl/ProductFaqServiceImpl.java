package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import com.demo.weloveShopSystem.entity.ProductFaq;
import com.demo.weloveShopSystem.mapper.ProductFaqMapper;
import com.demo.weloveShopSystem.service.ProductFaqService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class ProductFaqServiceImpl implements ProductFaqService {

    private final ProductFaqMapper productFaqMapper;

    @Override
    public List<ProductFaq> listByProductId(Long productId) {
        return productFaqMapper.selectList(
                new LambdaQueryWrapper<ProductFaq>()
                        .eq(ProductFaq::getProductId, productId)
                        .orderByAsc(ProductFaq::getSortOrder));
    }
}

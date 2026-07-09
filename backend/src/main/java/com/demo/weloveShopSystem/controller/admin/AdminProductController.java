package com.demo.weloveShopSystem.controller.admin;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Product;
import com.demo.weloveShopSystem.mapper.ProductMapper;
import com.demo.weloveShopSystem.service.ProductService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 后台商品管理控制器。
 * <p>
 * 覆盖商品分页筛选、上下架状态维护、字段整体更新、销量/库存维度的统计以及
 * 品牌枚举下拉。库存 stock 字段目前挂在 ProductSku 上而不是 Product,
 * 所以这里 lowStock/outOfStock 走 SKU 表更准,后续再改造。
 */
@RestController
@RequestMapping("/api/admin/product")
@RequiredArgsConstructor
public class AdminProductController {

    private final ProductService productService;
    private final ProductMapper productMapper;

    /**
     * 商品分页搜索。keyword 会联合搜 title/brand/tags 三个字段;
     * sortBy 白名单未做校验,前端目前只传 id/base_price/sales_count/rating 几种。
     */
    @GetMapping("/list")
    public Result<IPage<Product>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) Long categoryId,
            @RequestParam(required = false) String brand,
            @RequestParam(required = false) Integer status,
            @RequestParam(required = false) Double minPrice,
            @RequestParam(required = false) Double maxPrice,
            @RequestParam(defaultValue = "id") String sortBy,
            @RequestParam(defaultValue = "desc") String sortOrder) {
        QueryWrapper<Product> qw = new QueryWrapper<>();
        if (keyword != null && !keyword.isEmpty()) {
            qw.and(w -> w.like("title", keyword).or().like("brand", keyword).or().like("tags", keyword));
        }
        if (categoryId != null) {
            qw.eq("category_id", categoryId);
        }
        if (brand != null && !brand.isEmpty()) {
            qw.eq("brand", brand);
        }
        if (status != null) {
            qw.eq("status", status);
        }
        if (minPrice != null) {
            qw.ge("base_price", minPrice);
        }
        if (maxPrice != null) {
            qw.le("base_price", maxPrice);
        }
        qw.orderBy(true, "asc".equalsIgnoreCase(sortOrder), sortBy);
        return Result.success(productMapper.selectPage(new Page<>(page, size), qw));
    }

    /** 上下架:status=1 上架、0 下架。 */
    @PutMapping("/{id}/status")
    public Result<Void> updateStatus(@PathVariable Long id, @RequestParam int status) {
        Product product = productService.getById(id);
        if (product == null) {
            return Result.error("商品不存在");
        }
        product.setStatus(status);
        productMapper.updateById(product);
        return Result.success(null);
    }

    /** 用请求体整体覆盖更新商品字段,path 里的 id 会覆盖 body 里的 id 防前端串错。 */
    @PutMapping("/{id}")
    public Result<Product> update(@PathVariable Long id, @RequestBody Product product) {
        product.setId(id);
        productMapper.updateById(product);
        return Result.success(productService.getById(id));
    }

    /**
     * 商品状态概览 + 品牌/分类 Top10 分布。
     * TODO: lowStock/outOfStock 目前用 Product 直接查,严格意义上库存应从
     *       ProductSku 聚合,后续单独出一个统计接口。
     */
    @GetMapping("/stats")
    public Result<Map<String, Object>> stats() {
        Map<String, Object> stats = new HashMap<>();
        stats.put("total", productMapper.selectCount(null));
        stats.put("online", productMapper.selectCount(new QueryWrapper<Product>().eq("status", 1)));
        stats.put("offline", productMapper.selectCount(new QueryWrapper<Product>().eq("status", 0)));

        QueryWrapper<Product> brandQw = new QueryWrapper<>();
        brandQw.select("brand, count(*) as count").groupBy("brand").orderByDesc("count").last("limit 10");
        stats.put("brandDistribution", productMapper.selectMaps(brandQw));

        QueryWrapper<Product> catQw = new QueryWrapper<>();
        catQw.select("category_id, count(*) as count").groupBy("category_id").orderByDesc("count").last("limit 10");
        stats.put("categoryDistribution", productMapper.selectMaps(catQw));
        return Result.success(stats);
    }

    /** 品牌下拉列表,去重非空,前端筛选控件用。 */
    @GetMapping("/brands")
    public Result<List<String>> brands() {
        QueryWrapper<Product> qw = new QueryWrapper<>();
        qw.select("distinct brand").isNotNull("brand").ne("brand", "");
        return Result.success(productMapper.selectObjs(qw).stream()
                .map(Object::toString)
                .collect(Collectors.toList()));
    }
}

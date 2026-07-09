package com.demo.weloveShopSystem.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.*;
import com.demo.weloveShopSystem.service.*;
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
    private final ProductSkuService productSkuService;
    private final ProductImageService productImageService;
    private final ProductReviewService productReviewService;
    private final ProductFaqService productFaqService;

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

    /** 查询商品详情，包含 SKU、图片、评价和 FAQ。 */
    @GetMapping("/{id}")
    public Result<Map<String, Object>> detail(@PathVariable Long id) {
        Product product = productService.getById(id);
        if (product == null) {
            return Result.error("商品不存在");
        }

        Map<String, Object> detail = new HashMap<>();
        detail.put("product", product);
        detail.put("skus", productSkuService.listByProductId(id));
        detail.put("images", productImageService.listByProductId(id));
        detail.put("reviews", productReviewService.listByProductId(id, 10));
        detail.put("faqs", productFaqService.listByProductId(id));
        return Result.success(detail);
    }

    /** 查询商品 SKU 列表。 */
    @GetMapping("/{id}/skus")
    public Result<List<ProductSku>> skus(@PathVariable Long id) {
        return Result.success(productSkuService.listByProductId(id));
    }

    /** 查询商品评价列表。 */
    @GetMapping("/{id}/reviews")
    public Result<List<ProductReview>> reviews(
            @PathVariable Long id,
            @RequestParam(defaultValue = "10") int limit) {
        return Result.success(productReviewService.listByProductId(id, limit));
    }

    /**
     * 当前用户提交商品评价。
     * <p>
     * userId 从 SecurityContext 中的 JWT 主体解析,不信任任何客户端传入的用户身份。
     */
    @PostMapping("/{id}/reviews")
    public Result<ProductReview> submitReview(
            @PathVariable Long id,
            @RequestParam Integer rating,
            @RequestParam String content) {
        Long userId = Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
        return Result.success(productReviewService.submitReview(userId, id, rating, content));
    }

    /** 查询商品常见问答。 */
    @GetMapping("/{id}/faqs")
    public Result<List<ProductFaq>> faqs(@PathVariable Long id) {
        return Result.success(productFaqService.listByProductId(id));
    }

    /** 查询商品图片列表。 */
    @GetMapping("/{id}/images")
    public Result<List<ProductImage>> images(@PathVariable Long id) {
        return Result.success(productImageService.listByProductId(id));
    }
}

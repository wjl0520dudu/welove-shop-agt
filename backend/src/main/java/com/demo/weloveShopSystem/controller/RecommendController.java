package com.demo.weloveShopSystem.controller;


import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.UserBrowseHistory;
import com.demo.weloveShopSystem.entity.UserFavorite;
import com.demo.weloveShopSystem.service.RecommendationLogService;
import com.demo.weloveShopSystem.service.UserBrowseHistoryService;
import com.demo.weloveShopSystem.service.UserFavoriteService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 用户推荐反馈、收藏和浏览历史控制器。
 */
@RestController
@RequestMapping("/api/recommend")
@RequiredArgsConstructor
public class RecommendController {

    private final UserFavoriteService userFavoriteService;
    private final UserBrowseHistoryService userBrowseHistoryService;
    private final RecommendationLogService recommendationLogService;

    /** 从 Spring Security 上下文获取当前登录用户 ID。 */
    private Long getCurrentUserId() {
        return Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
    }

    /** 记录商品浏览行为。 */
    @PostMapping("/browse")
    public Result<Void> recordBrowse(@RequestBody UserBrowseHistory history) {
        history.setUserId(getCurrentUserId());
        userBrowseHistoryService.saveOrUpdate(history);
        return Result.success(null);
    }

    /** 添加商品收藏。 */
    @PostMapping("/favorite/add")
    public Result<Void> addFavorite(@RequestParam Long productId) {
        userFavoriteService.addFavorite(getCurrentUserId(), productId);
        return Result.success(null);
    }

    /** 取消商品收藏。 */
    @PostMapping("/favorite/remove")
    public Result<Void> removeFavorite(@RequestParam Long productId) {
        userFavoriteService.removeFavorite(getCurrentUserId(), productId);
        return Result.success(null);
    }

    /** 查询当前用户收藏列表。 */
    @GetMapping("/favorite/list")
    public Result<List<UserFavorite>> listFavorites() {
        return Result.success(userFavoriteService.listByUserId(getCurrentUserId()));
    }

    /** 提交推荐反馈。 */
    @PostMapping("/feedback")
    public Result<Void> feedback(@RequestParam Long id, @RequestParam Integer feedback) {
        recommendationLogService.updateFeedback(id, feedback);
        return Result.success(null);
    }


    /** 查询当前用户浏览历史。 */
    @GetMapping("/browse/history")
    public Result<List<UserBrowseHistory>> browseHistory() {
        return Result.success(userBrowseHistoryService.listByUserId(getCurrentUserId()));
    }

    /** 删除当前用户的某条浏览历史。 */
    @DeleteMapping("/browse/history/{id}")
    public Result<String> deleteHistory(@PathVariable Long id) {
        userBrowseHistoryService.deleteHistory(getCurrentUserId(), id);
        return Result.success("已删除");
    }
}

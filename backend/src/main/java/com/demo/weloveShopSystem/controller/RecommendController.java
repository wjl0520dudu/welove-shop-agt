package com.demo.weloveShopSystem.controller;


import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.UserFavorite;
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

    /** 从 Spring Security 上下文获取当前登录用户 ID。 */
    private Long getCurrentUserId() {
        return Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
    }


    /** 查询当前用户收藏列表。 */
    @GetMapping("/favorite/list")
    public Result<List<UserFavorite>> listFavorites() {
        return Result.success(userFavoriteService.listByUserId(getCurrentUserId()));
    }

}

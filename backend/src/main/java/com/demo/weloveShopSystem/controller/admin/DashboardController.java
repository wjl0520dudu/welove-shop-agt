package com.demo.weloveShopSystem.controller.admin;

import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.dto.DashboardStats;
import com.demo.weloveShopSystem.service.DashboardService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 后台仪表盘控制器。
 * <p>
 * 目前只暴露一个聚合统计接口;后续如果拆细维度(例如仅拿 clickRate 或
 * 仅拿 hotProducts),再往这里加即可,DashboardService 已按方法级拆分。
 */
@RestController
@RequestMapping("/api/admin/dashboard")
@RequiredArgsConstructor
public class DashboardController {

    private final DashboardService dashboardService;

    /** 获取后台首页统计数据。 */
    @GetMapping("/stat")
    public Result<DashboardStats> getStats() {
        return Result.success(dashboardService.getStats());
    }
}

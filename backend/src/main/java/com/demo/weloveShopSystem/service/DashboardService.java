package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.dto.DashboardStats;

/**
 * 后台仪表盘统计服务接口。
 */
public interface DashboardService {

    /** 获取后台首页统计指标,一次查询多张表并组装成 DashboardStats。 */
    DashboardStats getStats();
}

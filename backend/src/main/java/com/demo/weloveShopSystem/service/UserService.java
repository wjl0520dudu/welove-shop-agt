package com.demo.weloveShopSystem.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.demo.weloveShopSystem.entity.User;

/**
 * 用户管理服务接口。
 */
public interface UserService extends IService<User> {
    /**
     * 更新用户状态
     * @param userId
     * @param status
     */
    void updateStatus(Long userId, Integer status);
}

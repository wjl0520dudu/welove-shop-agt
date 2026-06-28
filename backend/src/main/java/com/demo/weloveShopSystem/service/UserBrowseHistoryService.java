package com.demo.weloveShopSystem.service;



import com.demo.weloveShopSystem.entity.UserBrowseHistory;

import java.util.List;

/**
 * 用户浏览历史服务接口。
 */
public interface UserBrowseHistoryService {
    /** 保存或更新用户浏览历史。 */
    void saveOrUpdate(UserBrowseHistory history);
    /** 查询用户浏览历史列表。 */
    List<UserBrowseHistory> listByUserId(Long userId);
    /** 删除用户指定浏览历史。 */
    void deleteHistory(Long userId, Long historyId);
}

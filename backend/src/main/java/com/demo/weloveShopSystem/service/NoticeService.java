package com.demo.weloveShopSystem.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.demo.weloveShopSystem.entity.Notice;

import java.util.List;

/**
 * 公告服务接口。
 */
public interface NoticeService extends IService<Notice> {
    /** 查询当前启用中的公告列表,按创建时间倒序。 */
    List<Notice> getActiveNotices();
}

package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.demo.weloveShopSystem.entity.Notice;
import com.demo.weloveShopSystem.mapper.NoticeMapper;
import com.demo.weloveShopSystem.service.NoticeService;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class NoticeServiceImpl extends ServiceImpl<NoticeMapper, Notice> implements NoticeService {

    @Override
    public List<Notice> getActiveNotices() {
        return this.list(new LambdaQueryWrapper<Notice>()
                .eq(Notice::getIsActive, true)
                .orderByDesc(Notice::getCreateTime));
    }
}

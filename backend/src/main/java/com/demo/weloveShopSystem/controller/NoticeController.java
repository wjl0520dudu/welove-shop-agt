package com.demo.weloveShopSystem.controller;

import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Notice;
import com.demo.weloveShopSystem.service.NoticeService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 用户侧公告控制器。
 * <p>
 * 前缀统一放在 /api/notice 下,与项目其他前台接口保持一致,方便 Security 用 /api/** 统一处理放行规则。
 * Bean 名前缀 UserNoticeController 用于与后台管理侧的 admin/NoticeController 区分开,避免同名冲突。
 */
@RestController("userNoticeController")
@RequestMapping("/api/notice")
@RequiredArgsConstructor
public class NoticeController {

    private final NoticeService noticeService;

    /** 查询当前启用中的公告列表,前端一般取第一条做全站顶部横幅展示。 */
    @GetMapping("/latest")
    public Result<List<Notice>> getLatestNotices() {
        return Result.success(noticeService.getActiveNotices());
    }
}

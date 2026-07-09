package com.demo.weloveShopSystem.controller.admin;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Notice;
import com.demo.weloveShopSystem.service.NoticeService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * 后台公告管理控制器。
 * <p>
 * 与前台 userNoticeController 分开挂在 /api/admin/notice,只有 ADMIN 可以增删改;
 * 前台 /api/notice/latest 只走查询。Bean 名默认为 noticeController,
 * 与前台 Bean 名 userNoticeController 区分,避免同名冲突。
 */
@RestController
@RequestMapping("/api/admin/notice")
@RequiredArgsConstructor
public class NoticeController {

    private final NoticeService noticeService;

    /** 分页查询公告列表。 */
    @GetMapping("/list")
    public Result<Page<Notice>> list(@RequestParam(defaultValue = "1") Integer page,
                                     @RequestParam(defaultValue = "10") Integer size) {
        return Result.success(noticeService.page(new Page<>(page, size)));
    }

    /** 新增公告。 */
    @PostMapping("/add")
    public Result<String> add(@RequestBody Notice notice) {
        noticeService.save(notice);
        return Result.success("发布成功");
    }

    /** 更新公告。 */
    @PutMapping("/update")
    public Result<String> update(@RequestBody Notice notice) {
        noticeService.updateById(notice);
        return Result.success("更新成功");
    }

    /** 删除公告。 */
    @DeleteMapping("/delete/{id}")
    public Result<String> delete(@PathVariable Long id) {
        noticeService.removeById(id);
        return Result.success("删除成功");
    }
}

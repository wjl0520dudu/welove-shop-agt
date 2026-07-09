package com.demo.weloveShopSystem.controller;

import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.KnowledgeDoc;
import com.demo.weloveShopSystem.service.KnowledgeService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 知识库文档控制器。
 * <p>
 * 这几个接口既服务于用户侧的知识浏览、也服务于运营侧的知识灌入,后台管理端还会挂一层
 * admin/KnowledgeInspectionController 做额外的分析,当前控制器只负责 CRUD 语义。
 */
@RestController
@RequestMapping("/api/knowledge")
@RequiredArgsConstructor
public class KnowledgeController {

    private final KnowledgeService knowledgeService;

    /**
     * 上传知识文档并触发 AI 解析入库。
     * <p>
     * 走 multipart/form-data,file 必填,categoryId 可选,不传则为通用知识。
     */
    @PostMapping("/upload")
    public Result<KnowledgeDoc> upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam(required = false) Long categoryId) {
        return Result.success(knowledgeService.uploadDoc(file, categoryId));
    }

    /** 查询知识文档列表,可按 categoryId 过滤。 */
    @GetMapping("/list")
    public Result<List<KnowledgeDoc>> list(@RequestParam(required = false) Long categoryId) {
        return Result.success(knowledgeService.listDocs(categoryId));
    }

    /** 删除知识文档,级联清理对象存储与向量索引。 */
    @DeleteMapping("/{id}")
    public Result<String> delete(@PathVariable Long id) {
        knowledgeService.deleteDoc(id);
        return Result.success("Deleted successfully");
    }

    /**
     * 查看知识文档详情。
     * <p>
     * userId 一律从 JWT 主体解析,不接受客户端传入,预留给后续访问审计使用。
     */
    @GetMapping("/view/{id}")
    public Result<KnowledgeDoc> view(@PathVariable Long id) {
        Long userId = Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
        return Result.success(knowledgeService.viewDoc(id, userId));
    }
}

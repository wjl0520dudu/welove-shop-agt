package com.demo.weloveShopSystem.controller.admin;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.KnowledgeDoc;
import com.demo.weloveShopSystem.entity.QaLog;
import com.demo.weloveShopSystem.entity.User;
import com.demo.weloveShopSystem.service.AdminService;
import com.demo.weloveShopSystem.service.AiService;
import com.demo.weloveShopSystem.service.KnowledgeService;
import com.demo.weloveShopSystem.service.QaLogService;
import com.demo.weloveShopSystem.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

/**
 * 后台基础管理控制器。
 * <p>
 * 覆盖:管理员登录、用户列表/状态更新、知识库上传/删除/查询/重试解析、问答日志分页。
 * 所有非 login 接口都受 AdminInterceptor + SecurityConfig 双层校验保护,
 * 只有携带 ADMIN 角色的 token 才能访问。
 */
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class AdminController {

    private final AdminService adminService;
    private final UserService userService;
    private final KnowledgeService knowledgeService;
    private final AiService aiService;
    private final QaLogService qaLogService;

    /**
     * 管理员登录。请求体形如 { "username": "...", "password": "..." }。
     * 走 Map 而不是专门 DTO,是因为后台登录目前只需要这两个字段,再抽 DTO 反而冗余。
     */
    @PostMapping("/login")
    public Result<Map<String, Object>> login(@RequestBody Map<String, String> loginRequest) {
        String username = loginRequest.get("username");
        String password = loginRequest.get("password");
        return Result.success(adminService.login(username, password));
    }

    /** 分页查询用户列表,默认第 1 页、每页 10 条。 */
    @GetMapping("/users")
    public Result<IPage<User>> listUsers(@RequestParam(defaultValue = "1") Integer page,
                                         @RequestParam(defaultValue = "10") Integer size) {
        return Result.success(userService.page(new Page<>(page, size)));
    }

    /** 更新指定用户的状态(0 禁用 / 1 启用)。 */
    @PostMapping("/users/{userId}/status")
    public Result<Void> updateUserStatus(@PathVariable Long userId, @RequestParam Integer status) {
        userService.updateStatus(userId, status);
        return Result.success(null);
    }

    /** 上传知识库文档,与 /api/knowledge/upload 语义一致,只是路径挂在后台。 */
    @PostMapping("/knowledge/upload")
    public Result<KnowledgeDoc> uploadDoc(@RequestParam("file") MultipartFile file,
                                          @RequestParam(required = false) Long categoryId) {
        return Result.success(knowledgeService.saveDoc(file, categoryId));
    }

    /** 删除知识库文档,级联清理对象存储与向量索引。 */
    @DeleteMapping("/knowledge/{id}")
    public Result<Void> deleteDoc(@PathVariable Long id) {
        knowledgeService.deleteDoc(id);
        return Result.success(null);
    }

    /** 查询知识库文档列表,可按 categoryId 过滤。 */
    @GetMapping("/knowledge/list")
    public Result<List<KnowledgeDoc>> listDocs(@RequestParam(required = false) Long categoryId) {
        return Result.success(knowledgeService.listDocs(categoryId));
    }

    /**
     * 重新触发已上传文档的 AI 解析,常用于首次解析失败后的重跑。
     * 请求体: { "id": 123, "filePath": "..." }。
     */
    @PostMapping("/knowledge/retry-parse")
    public Result<Void> retryParse(@RequestBody Map<String, Object> request) {
        Long id = Long.parseLong(request.get("id").toString());
        String filePath = (String) request.get("filePath");
        aiService.parseDocument(filePath, id);
        return Result.success(null);
    }

    /** 分页查询问答日志,按 createTime 倒序。 */
    @GetMapping("/logs")
    public Result<IPage<QaLog>> listLogs(@RequestParam(defaultValue = "1") Integer page,
                                         @RequestParam(defaultValue = "10") Integer size) {
        Page<QaLog> logPage = new Page<>(page, size);
        return Result.success(qaLogService.page(logPage,
                new LambdaQueryWrapper<QaLog>().orderByDesc(QaLog::getCreateTime)));
    }
}

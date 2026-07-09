package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.entity.KnowledgeDoc;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 知识库文档服务接口。
 * <p>
 * 负责文档上传(云存储 OSS 或本地)、落库、触发 AI 解析建立向量索引、以及后台管理端的删除与查看。
 */
public interface KnowledgeService {

    /**
     * 上传知识文档并触发 AI 解析。
     *
     * @param file       上传的文件
     * @param categoryId 所属分类 ID,可为空
     * @return 落库后的知识文档记录,状态初始为 PENDING
     */
    KnowledgeDoc uploadDoc(MultipartFile file, Long categoryId);

    /** 保存知识文档的兼容别名,内部复用 uploadDoc,方便旧代码平滑迁移。 */
    default KnowledgeDoc saveDoc(MultipartFile file, Long categoryId) {
        return uploadDoc(file, categoryId);
    }

    /**
     * 查询知识文档列表。
     *
     * @param categoryId 分类 ID,为空时返回全部
     */
    List<KnowledgeDoc> listDocs(Long categoryId);

    /**
     * 删除知识文档,同时清理对应的对象存储文件与 AI 侧的向量索引。
     */
    void deleteDoc(Long docId);

    /** 查看知识文档详情,userId 预留用于后续做访问审计。 */
    KnowledgeDoc viewDoc(Long docId, Long userId);
}

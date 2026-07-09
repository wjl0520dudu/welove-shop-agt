package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.weloveShopSystem.entity.KnowledgeDoc;
import com.demo.weloveShopSystem.mapper.KnowledgeDocMapper;
import com.demo.weloveShopSystem.service.AiService;
import com.demo.weloveShopSystem.service.KnowledgeService;
import com.qiniu.common.QiniuException;
import com.qiniu.http.Response;
import com.qiniu.storage.BucketManager;
import com.qiniu.storage.Configuration;
import com.qiniu.storage.Region;
import com.qiniu.storage.UploadManager;
import com.qiniu.util.Auth;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 知识库文档服务实现。
 * <p>
 * 上传路径按顺序决定:配置了云存储 accessKey 时优先走对象存储,否则落到本地 uploadDir。
 * 落库后立即调用 AiService 触发解析建索;删除同样级联清理对象存储与向量索引。
 * <p>
 * TODO: 项目最终使用的对象存储供应商待定,当前先用一套兼容 SDK 完成上传/删除动作。
 *       后续切换供应商时,只需替换 uploadToCloud / deleteFromCloud 两个私有方法的实现,
 *       接口契约与配置 key(cloud.storage.*)保持不变。
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class KnowledgeServiceImpl implements KnowledgeService {

    private final KnowledgeDocMapper knowledgeDocMapper;
    private final AiService aiService;

    /** 云存储 accessKey,未配置时自动降级到本地磁盘。 */
    @Value("${cloud.storage.accessKey:}")
    private String cloudAccessKey;
    /** 云存储 secretKey。 */
    @Value("${cloud.storage.secretKey:}")
    private String cloudSecretKey;
    /** 云存储 bucket 名。 */
    @Value("${cloud.storage.bucket:}")
    private String cloudBucket;
    /** 云存储访问域名,拼装外链 URL 使用。 */
    @Value("${cloud.storage.domain:}")
    private String cloudDomain;

    /** 本地存储目录,仅在未启用云存储时生效。 */
    @Value("${upload.dir:./uploads}")
    private String uploadDir;

    @Override
    public KnowledgeDoc uploadDoc(MultipartFile file, Long categoryId) {
        String fileName = file.getOriginalFilename();
        if (fileName == null) {
            fileName = "unknown";
        }
        String savedFileName = UUID.randomUUID() + "_" + fileName;
        String filePath;

        // 1. 判断走对象存储还是本地磁盘
        if (isCloudStorageEnabled()) {
            try {
                uploadToCloud("documents/" + savedFileName, file.getInputStream());
                String domain = cloudDomain.endsWith("/")
                        ? cloudDomain.substring(0, cloudDomain.length() - 1)
                        : cloudDomain;
                // 域名兜底补齐协议头,避免生成的 URL 前端拼接失败。
                if (!domain.startsWith("http://") && !domain.startsWith("https://")) {
                    domain = "http://" + domain;
                }
                filePath = domain + "/documents/" + savedFileName;
            } catch (IOException e) {
                log.error("Cloud storage upload failed", e);
                throw new RuntimeException("Cloud storage upload failed");
            }
        } else {
            try {
                File dir = new File(uploadDir);
                if (!dir.exists() && !dir.mkdirs()) {
                    throw new IOException("Failed to create upload dir: " + uploadDir);
                }
                File savedFile = new File(dir, savedFileName);
                file.transferTo(savedFile);
                filePath = savedFile.getAbsolutePath();
            } catch (IOException e) {
                log.error("Local file save failed", e);
                throw new RuntimeException("Local file save failed");
            }
        }

        // 2. 落库,状态先置为 PENDING,等待 AI 侧解析完成再回写。
        KnowledgeDoc doc = new KnowledgeDoc();
        doc.setDocName(fileName);
        doc.setFilePath(filePath);
        doc.setCategoryId(categoryId);
        doc.setStatus("PENDING");
        doc.setCreateTime(LocalDateTime.now());
        knowledgeDocMapper.insert(doc);

        // 3. 触发 AI 服务解析并建立向量索引。
        aiService.parseDocument(filePath, doc.getId());
        return doc;
    }

    @Override
    public List<KnowledgeDoc> listDocs(Long categoryId) {
        LambdaQueryWrapper<KnowledgeDoc> query = new LambdaQueryWrapper<>();
        if (categoryId != null) {
            query.eq(KnowledgeDoc::getCategoryId, categoryId);
        }
        query.orderByDesc(KnowledgeDoc::getCreateTime);
        return knowledgeDocMapper.selectList(query);
    }

    @Override
    public void deleteDoc(Long docId) {
        KnowledgeDoc doc = knowledgeDocMapper.selectById(docId);
        if (doc == null) {
            log.warn("Attempt to delete non-existent document: id={}", docId);
            return;
        }
        log.info("Deleting document: id={}, name={}", docId, doc.getDocName());

        // 1. 云存储对象清理:未开启或不是 http 前缀就跳过。
        if (isCloudStorageEnabled()
                && doc.getFilePath() != null && doc.getFilePath().startsWith("http")) {
            try {
                String domain = cloudDomain.endsWith("/")
                        ? cloudDomain.substring(0, cloudDomain.length() - 1)
                        : cloudDomain;
                String domainNoProtocol = domain.replace("http://", "").replace("https://", "");
                String filePath = doc.getFilePath();
                String key = filePath;
                if (filePath.contains(domainNoProtocol)) {
                    int index = filePath.indexOf(domainNoProtocol);
                    if (index + domainNoProtocol.length() + 1 < filePath.length()) {
                        key = filePath.substring(index + domainNoProtocol.length() + 1);
                    }
                }
                deleteFromCloud(key);
                log.info("Deleted object from cloud storage: key={}", key);
            } catch (Exception e) {
                log.error("Delete from cloud storage failed", e);
            }
        }

        // 2. AI 侧向量索引清理:失败不影响 DB 记录删除,只记日志。
        try {
            aiService.deleteDoc(docId);
            log.info("Deleted vector index for document: id={}", docId);
        } catch (Exception e) {
            log.error("Delete vector index failed", e);
        }

        // 3. 最后删 DB 主记录。
        knowledgeDocMapper.deleteById(docId);
        log.info("Document deleted successfully: id={}, name={}", docId, doc.getDocName());
    }

    @Override
    public KnowledgeDoc viewDoc(Long docId, Long userId) {
        // userId 参数当前未强校验,先透传下来给后续做访问审计使用。
        return knowledgeDocMapper.selectById(docId);
    }

    /** 是否启用了云存储:accessKey 有值就认为启用。 */
    private boolean isCloudStorageEnabled() {
        return cloudAccessKey != null && !cloudAccessKey.isEmpty();
    }

    /**
     * 上传对象到云存储。
     * <p>
     * 当前使用与阿里 OSS / 七牛 / 腾讯 COS 都兼容的一套 SDK 做占位实现,
     * 换厂商时替换此方法内部即可,方法签名保持不变。
     */
    private void uploadToCloud(String objectName, InputStream inputStream) {
        Configuration cfg = new Configuration(Region.autoRegion());
        UploadManager uploadManager = new UploadManager(cfg);
        Auth auth = Auth.create(cloudAccessKey, cloudSecretKey);
        String upToken = auth.uploadToken(cloudBucket);

        try {
            Response response = uploadManager.put(inputStream, objectName, upToken, null, null);
            log.info("Cloud storage upload success: {}", response.bodyString());
        } catch (QiniuException ex) {
            log.error("Cloud storage upload failed", ex);
            if (ex.response != null) {
                log.error("Cloud storage error response: {}", ex.response.toString());
            }
            throw new RuntimeException("Cloud storage upload failed");
        }
    }

    /** 从云存储删除对象。签名与 uploadToCloud 对称,换厂商只需替换实现。 */
    private void deleteFromCloud(String key) {
        Configuration cfg = new Configuration(Region.autoRegion());
        Auth auth = Auth.create(cloudAccessKey, cloudSecretKey);
        BucketManager bucketManager = new BucketManager(auth, cfg);
        try {
            bucketManager.delete(cloudBucket, key);
        } catch (QiniuException ex) {
            log.error("Cloud storage delete failed", ex);
            // 612 通常表示对象已不存在,可安全忽略,其他错误码继续抛出。
            if (ex.code() != 612) {
                throw new RuntimeException("Cloud storage delete failed");
            }
        }
    }
}

package com.demo.weloveShopSystem.common;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * URL 工具类，用于将相对路径转换为前端可直接访问的完整 URL。
 */
@Component
public class UrlUtil {

    /** 服务对外访问基础地址，未配置时默认使用本地后端地址。 */
    @Value("${server.base-url:http://localhost:8080}")
    private String baseUrl;

    /**
     * 将相对路径转换为完整 URL。
     *
     * @param relativePath 相对路径，例如 /api/chat/view/image/xxx
     * @return 完整 URL，例如 http://localhost:8080/api/chat/view/image/xxx
     */
    public String toAbsoluteUrl(String relativePath) {
        if (relativePath == null || relativePath.isEmpty()) {
            return relativePath;
        }
        if (relativePath.startsWith("http://") || relativePath.startsWith("https://")) {
            return relativePath;
        }
        if (!relativePath.startsWith("/")) {
            relativePath = "/" + relativePath;
        }
        return baseUrl + relativePath;
    }
}

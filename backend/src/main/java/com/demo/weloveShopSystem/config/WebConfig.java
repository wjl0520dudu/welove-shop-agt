package com.demo.weloveShopSystem.config;

import com.demo.weloveShopSystem.interceptor.AdminInterceptor;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.converter.StringHttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * Spring MVC 配置。
 * <p>
 * 负责三件事:
 *  1) 统一 JSON 与字符串响应的默认编码为 UTF-8,避免中文乱码;
 *  2) 注册 AdminInterceptor,把 /api/admin/** 除 /api/admin/login 外的请求
 *     交给拦截器做管理员身份二次校验;
 *  3) 把本地商品图片目录暴露成静态资源,便于前端直连访问,不必再走 Controller。
 */
@Configuration
@RequiredArgsConstructor
public class WebConfig implements WebMvcConfigurer {

    /** 管理员接口拦截器。 */
    private final AdminInterceptor adminInterceptor;

    /**
     * 商品图片本地根目录。
     * <p>
     * 生产环境应通过环境变量 PRODUCT_IMAGE_BASE_PATH 注入,默认值只作为本地
     * 开发兜底,避免 IDE 里跑不起来。
     */
    @Value("${product.image.base-path:./data/product-images}")
    private String productImageBasePath;

    /** 统一 JSON 和字符串响应的默认编码为 UTF-8。 */
    @Override
    public void extendMessageConverters(List<HttpMessageConverter<?>> converters) {
        for (HttpMessageConverter<?> converter : converters) {
            if (converter instanceof MappingJackson2HttpMessageConverter) {
                ((MappingJackson2HttpMessageConverter) converter).setDefaultCharset(StandardCharsets.UTF_8);
            }
            if (converter instanceof StringHttpMessageConverter) {
                ((StringHttpMessageConverter) converter).setDefaultCharset(StandardCharsets.UTF_8);
            }
        }
    }

    /** 注册管理员拦截器,拦截 /api/admin/** 下除登录外的请求。 */
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(adminInterceptor)
                .addPathPatterns("/api/admin/**")
                .excludePathPatterns("/api/admin/login");
    }

    /** 将本地商品图片目录映射为 /product-images/** 静态访问路径。 */
    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/product-images/**")
                .addResourceLocations("file:" + productImageBasePath + "/");
    }
}

package com.demo.weloveShopSystem.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * HTTP 客户端配置，用于调用 Python AI 服务或其他外部服务。
 */
@Configuration
public class RestTemplateConfig {

    /**
     * 同步 HTTP 客户端。
     * AI 服务响应可能较慢，所以读取超时时间设置为 3 分钟。
     */
    @Bean
    public RestTemplate restTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(180000);
        return new RestTemplate(factory);
    }

    /**
     * 响应式 HTTP 客户端，默认指向本地 Python 服务。
     */
    @Bean
    public WebClient webClient() {
        return WebClient.builder()
                .baseUrl("http://localhost:8000")
                .build();
    }
}

package com.welove.shop.trade.config;

import com.alipay.easysdk.factory.Factory;
import com.alipay.easysdk.kernel.Config;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;

/**
 * 支付宝 EasySDK 初始化。
 * <p>
 * 通过 {@code alipay.enabled=true} 触发(默认 false,降级到模拟支付)。
 * <p>
 * <b>说明</b>:EasySDK 用 {@link Factory} 单例承载配置,Spring 容器只负责在启动期
 * 调一次 {@code Factory.setOptions},之后业务代码按 pay-mode 调用
 * {@code Factory.Payment.Wap()} 或 {@code Factory.Payment.Page()}。
 */
@Slf4j
@Configuration
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "alipay", name = "enabled", havingValue = "true")
public class AlipayConfig {

    private final AlipayProperties alipayProperties;

    @PostConstruct
    public void init() {
        // gatewayUrl 形如 https://openapi.alipaydev.com/gateway.do
        // EasySDK 需要的是 host(去掉协议和 /gateway.do 后缀)
        String host = alipayProperties.getGatewayUrl()
                .replace("https://", "")
                .replace("http://", "")
                .replace("/gateway.do", "");

        Config config = new Config();
        config.protocol = alipayProperties.getProtocol();
        config.gatewayHost = host;
        config.appId = alipayProperties.getAppId();
        config.signType = alipayProperties.getSignType();
        config.merchantPrivateKey = alipayProperties.getAppPrivateKey();
        config.alipayPublicKey = alipayProperties.getAlipayPublicKey();
        // 注:EasySDK Config 不含 charset 字段,内部固定 UTF-8

        Factory.setOptions(config);
        log.info("[alipay] easysdk initialized, gateway={}, appId={}", host, alipayProperties.getAppId());
    }
}

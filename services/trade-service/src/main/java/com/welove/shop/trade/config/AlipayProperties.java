package com.welove.shop.trade.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * 支付宝支付配置属性。
 * <p>
 * 绑 {@code alipay.*} 配置段。沙箱/生产通用,通过环境变量切换。
 */
@Data
@Configuration
@ConfigurationProperties(prefix = "alipay")
public class AlipayProperties {

    /** 是否启用沙箱支付。false = 走原"模拟支付"路径(便于本地无配置时跑通)。 */
    private boolean enabled;

    /** 沙箱/生产 APPID。 */
    private String appId;

    /** 应用私钥(PKCS8 格式,无 -----BEGIN/END----- 头尾)。 */
    private String appPrivateKey;

    /** 支付宝公钥(注意:不是应用公钥,是沙箱/生产后台拿到的那段)。 */
    private String alipayPublicKey;

    /** 网关地址。沙箱以支付宝后台提供的地址为准;生产:https://openapi.alipay.com/gateway.do。 */
    private String gatewayUrl;

    /** 支付产品:wap=手机 H5 支付(默认),page=电脑网站支付。 */
    private String payMode = "wap";

    /** 协议:https/http。 */
    private String protocol = "https";

    /** 签名类型:固定 RSA2。 */
    private String signType = "RSA2";

    /** 字符集。 */
    private String charset = "UTF-8";

    /** 异步通知地址(必须公网 HTTPS)。 */
    private String notifyUrl;

    /** 同步跳转地址。 */
    private String returnUrl;

    /** 用户主动退出支付宝收银台后的 H5 地址。 */
    private String quitUrl;

    /**
     * 前端 H5 支付结果页 URL（returnUrl 同步跳转后会 302 到这个地址）。
     * <p>
     * 留空则降级:同步跳转直接返回 "支付完成,请回到订单列表查看状态"。
     * <p>
     * 建议配置:
     *   - dev:    http://localhost:5173/#/pages/payment/result
     *   - sandbox:https://你的公网域名/#/pages/payment/result
     *   - prod:   https://www.yourdomain.com/#/pages/payment/result
     */
    private String h5ReturnUrl;
}

package com.welove.shop.trade.service;

import com.welove.shop.trade.dto.PayStatusVO;

import java.util.Map;

/**
 * 支付服务。
 * <p>
 * 沙箱未启用时(alipay.enabled=false)走"模拟支付"路径,本地无任何外部依赖即可跑通。
 */
public interface PaymentService {

    /**
     * 发起支付宝网页支付(默认 H5 WAP,可配置切换为 PC Page)。
     * <p>
     * 返回收银台 form HTML,前端直接渲染会自动跳转到支付宝。
     * <p>
     * 沙箱未启用时:直接走"模拟支付"路径,1 秒后调用本服务自身的 notify 接口完成状态变更;
     * 仍返回与正式流程一致的响应(本期 MVP 简化为直接抛错,引导用户走 controller 中的兼容分支)。
     */
    String createPayPage(Long userId, Long orderId);

    /**
     * 处理支付宝异步通知(由 Controller 验签后调用)。
     * <p>
     * 入参是验签后的全部 form 参数(已剔除 sign / sign_type)。
     */
    void handlePayNotify(Map<String, String> params);

    /**
     * 主动查询支付状态(对账 / 前端轮询用)。
     */
    PayStatusVO queryTradeStatus(Long userId, Long orderId);

    /**
     * 关闭未支付订单(用户主动取消 / 超时前主动关单)。
     * <p>
     * 沙箱未启用时:仅本地 0 → 4。
     */
    void closePay(Long userId, Long orderId);
}

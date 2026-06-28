package com.demo.weloveShopSystem.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.demo.weloveShopSystem.dto.CreateOrderRequest;
import com.demo.weloveShopSystem.vo.OrderVO;


/**
 * 订单服务接口。
 */
public interface OrderService {
    /** 创建订单。 */
    OrderVO createOrder(Long userId, CreateOrderRequest request);
    /** 分页查询用户订单列表。 */
    IPage<OrderVO> listOrders(Long userId, Integer status, int page, int size);
    /** 查询订单详情。 */
    OrderVO getOrderDetail(Long userId, Long orderId);
    /** 支付订单。 */
    OrderVO payOrder(Long userId, Long orderId);
    /** 取消订单。 */
    OrderVO cancelOrder(Long userId, Long orderId);
    /** 确认收货。 */
    OrderVO confirmReceive(Long userId, Long orderId);
    /** 删除订单。 */
    void deleteOrder(Long userId, Long orderId);
}

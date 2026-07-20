package com.welove.shop.trade.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.welove.shop.common.core.exception.BizException;
import com.welove.shop.common.core.result.Result;
import com.welove.shop.trade.dto.CreateOrderRequest;
import com.welove.shop.trade.entity.Order;
import com.welove.shop.trade.entity.OrderItem;
import com.welove.shop.trade.exception.TradeErrorCode;
import com.welove.shop.trade.feign.ProductClient;
import com.welove.shop.trade.feign.UserClient;
import com.welove.shop.trade.feign.dto.AddressDTO;
import com.welove.shop.trade.feign.dto.ProductDTO;
import com.welove.shop.trade.feign.dto.ProductSkuDTO;
import com.welove.shop.trade.mapper.OrderItemMapper;
import com.welove.shop.trade.mapper.OrderMapper;
import com.welove.shop.trade.service.OrderService;
import com.welove.shop.trade.vo.OrderVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Random;
import java.util.stream.Collectors;

/**
 * 订单服务实现。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderServiceImpl implements OrderService {

    private static final DateTimeFormatter ORDER_NO_FMT = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductClient productClient;
    private final UserClient userClient;

    // ---------- 创建订单 ----------

    @Override
    @Transactional
    public OrderVO createOrder(Long userId, CreateOrderRequest request) {
        if (request.getItems() == null || request.getItems().isEmpty()) {
            throw new BizException(TradeErrorCode.ORDER_ITEMS_EMPTY, "订单明细不能为空");
        }

        // 1. Feign 拿地址,写快照
        AddressDTO address = fetchAddress(request.getAddressId());
        if (address == null || !userId.equals(address.getUserId())) {
            throw new BizException(TradeErrorCode.ADDRESS_NOT_FOUND_REMOTE, "收货地址不存在或不属于当前用户");
        }

        // 2. 批量 Feign 拿商品/SKU
        List<Long> productIds = request.getItems().stream()
                .map(CreateOrderRequest.OrderItemDto::getProductId)
                .distinct()
                .toList();
        List<Long> skuIds = request.getItems().stream()
                .map(CreateOrderRequest.OrderItemDto::getSkuId)
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        Map<Long, ProductDTO> productMap = fetchProducts(productIds);
        Map<Long, ProductSkuDTO> skuMap = fetchSkus(skuIds);

        // 3. 计算总额 + 构建 OrderItem 快照
        BigDecimal totalAmount = BigDecimal.ZERO;
        List<OrderItem> items = new ArrayList<>();
        for (CreateOrderRequest.OrderItemDto dto : request.getItems()) {
            ProductDTO product = productMap.get(dto.getProductId());
            if (product == null) {
                throw new BizException(TradeErrorCode.PRODUCT_NOT_FOUND_REMOTE,
                        "商品不存在: " + dto.getProductId());
            }
            if (product.getStatus() != null && product.getStatus() == 0) {
                throw new BizException(TradeErrorCode.PRODUCT_OFF_SHELF,
                        "商品已下架: " + product.getTitle());
            }
            ProductSkuDTO sku = null;
            if (dto.getSkuId() != null) {
                sku = skuMap.get(dto.getSkuId());
                if (sku == null) {
                    throw new BizException(TradeErrorCode.SKU_NOT_FOUND_REMOTE,
                            "SKU 不存在: " + dto.getSkuId());
                }
            }

            // 单价:SKU 价 > 商品基础价
            BigDecimal price = sku != null ? sku.getPrice() : product.getBasePrice();
            BigDecimal subtotal = price.multiply(BigDecimal.valueOf(dto.getQuantity()));

            OrderItem item = new OrderItem();
            item.setProductId(product.getId());
            item.setProductTitle(product.getTitle());
            item.setProductImage(product.getImageUrl());
            item.setSkuId(dto.getSkuId());
            item.setSkuProperties(formatSkuProperties(sku));
            item.setPrice(price);
            item.setQuantity(dto.getQuantity());
            item.setTotalAmount(subtotal);
            items.add(item);

            totalAmount = totalAmount.add(subtotal);
        }

        // 4. 生成订单号 + 插入 order
        BigDecimal freight = BigDecimal.ZERO;
        Order order = new Order();
        order.setUserId(userId);
        order.setOrderNo(generateOrderNo());
        order.setStatus(0);
        order.setTotalAmount(totalAmount);
        order.setPayAmount(totalAmount.add(freight));
        order.setFreightAmount(freight);
        order.setAddressId(address.getId());
        order.setReceiverName(StringUtils.hasText(request.getReceiverName())
                ? request.getReceiverName() : address.getReceiverName());
        order.setReceiverPhone(StringUtils.hasText(request.getReceiverPhone())
                ? request.getReceiverPhone() : address.getPhone());
        order.setReceiverAddress(buildReceiverAddress(address));
        order.setRemark(request.getRemark());
        LocalDateTime now = LocalDateTime.now();
        order.setCreateTime(now);
        order.setUpdateTime(now);
        orderMapper.insert(order);

        // 5. 插入 order_item
        for (OrderItem item : items) {
            item.setOrderId(order.getId());
            orderItemMapper.insert(item);
        }

        log.info("[order] created: userId={}, orderNo={}, totalAmount={}",
                userId, order.getOrderNo(), totalAmount);

        return OrderVO.from(order, items);
    }

    // ---------- 查询 ----------

    @Override
    public IPage<OrderVO> listOrders(Long userId, Integer status, int page, int size) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<Order>()
                .eq(Order::getUserId, userId)
                .orderByDesc(Order::getCreateTime);
        if (status != null) {
            wrapper.eq(Order::getStatus, status);
        }
        IPage<Order> orderPage = orderMapper.selectPage(new Page<>(page, size), wrapper);

        // 批量查明细
        List<Long> orderIds = orderPage.getRecords().stream().map(Order::getId).toList();
        Map<Long, List<OrderItem>> itemMap;
        if (orderIds.isEmpty()) {
            itemMap = Collections.emptyMap();
        } else {
            List<OrderItem> allItems = orderItemMapper.selectList(
                    new LambdaQueryWrapper<OrderItem>().in(OrderItem::getOrderId, orderIds));
            itemMap = allItems.stream().collect(Collectors.groupingBy(OrderItem::getOrderId));
        }

        Page<OrderVO> voPage = new Page<>(orderPage.getCurrent(), orderPage.getSize(), orderPage.getTotal());
        voPage.setRecords(orderPage.getRecords().stream()
                .map(o -> OrderVO.from(o, itemMap.getOrDefault(o.getId(), Collections.emptyList())))
                .toList());
        return voPage;
    }

    @Override
    public OrderVO getOrderDetail(Long userId, Long orderId) {
        Order order = requireOwnedOrder(userId, orderId);
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, orderId));
        return OrderVO.from(order, items);
    }

    // ---------- 状态流转 ----------

    @Override
    @Transactional
    public void payOrder(Long userId, Long orderId) {
        Order order = requireOwnedOrder(userId, orderId);
        if (order.getStatus() != 0) {
            throw new BizException(TradeErrorCode.ORDER_STATUS_INVALID, "订单状态不允许支付");
        }
        LocalDateTime now = LocalDateTime.now();
        order.setStatus(1);
        order.setPayTime(now);
        order.setUpdateTime(now);
        orderMapper.updateById(order);
    }

    @Override
    @Transactional
    public void markPaidByCallback(String outTradeNo, String tradeNo, String totalAmount, String channel) {
        if (outTradeNo == null || outTradeNo.isEmpty()) {
            throw new BizException(TradeErrorCode.PAY_NOTIFY_INVALID, "out_trade_no 缺失");
        }
        Order order = orderMapper.selectOne(
                new LambdaQueryWrapper<Order>().eq(Order::getOrderNo, outTradeNo));
        if (order == null) {
            throw new BizException(TradeErrorCode.ORDER_NOT_FOUND, "订单不存在:" + outTradeNo);
        }
        // 金额校验(防伪造)
        if (totalAmount != null && !totalAmount.isEmpty()
                && new BigDecimal(totalAmount).compareTo(order.getPayAmount()) != 0) {
            log.warn("[order-callback] amount mismatch, orderNo={}, notify={}, local={}",
                    outTradeNo, totalAmount, order.getPayAmount());
            throw new BizException(TradeErrorCode.PAY_NOTIFY_INVALID, "金额不一致");
        }
        // 幂等:仅 status=0 时更新,已处理直接跳过
        if (order.getStatus() != 0) {
            log.info("[order-callback] already processed, orderNo={}, status={}",
                    outTradeNo, order.getStatus());
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        order.setStatus(1);
        order.setPayTime(now);
        order.setUpdateTime(now);
        order.setTradeNo(tradeNo);
        order.setPayChannel(channel);
        orderMapper.updateById(order);
        log.info("[order-callback] order paid, orderNo={}, tradeNo={}, channel={}",
                outTradeNo, tradeNo, channel);
    }

    @Override
    @Transactional
    public void cancelOrder(Long userId, Long orderId) {
        Order order = requireOwnedOrder(userId, orderId);
        if (order.getStatus() != 0) {
            throw new BizException(TradeErrorCode.ORDER_CANNOT_CANCEL, "仅未付款订单可取消");
        }
        order.setStatus(4);
        order.setUpdateTime(LocalDateTime.now());
        orderMapper.updateById(order);
    }

    @Override
    @Transactional
    public void confirmReceive(Long userId, Long orderId) {
        Order order = requireOwnedOrder(userId, orderId);
        if (order.getStatus() != 1 && order.getStatus() != 2) {
            throw new BizException(TradeErrorCode.ORDER_STATUS_INVALID, "订单状态不允许确认收货");
        }
        LocalDateTime now = LocalDateTime.now();
        order.setStatus(3);
        order.setReceiveTime(now);
        order.setUpdateTime(now);
        orderMapper.updateById(order);
    }

    @Override
    @Transactional
    public void deleteOrder(Long userId, Long orderId) {
        Order order = requireOwnedOrder(userId, orderId);
        if (order.getStatus() != 3 && order.getStatus() != 4) {
            throw new BizException(TradeErrorCode.ORDER_CANNOT_DELETE, "仅已完成/已取消订单可删除");
        }
        orderItemMapper.delete(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, orderId));
        orderMapper.deleteById(orderId);
    }

    @Override
    @Transactional
    public void updateStatus(Order order, Integer status) {
        order.setStatus(status);
        order.setUpdateTime(LocalDateTime.now());
        orderMapper.updateById(order);
    }

    @Override
    public Long findIdByOrderNo(String orderNo) {
        if (orderNo == null || orderNo.isEmpty()) return null;
        Order order = orderMapper.selectOne(
                new LambdaQueryWrapper<Order>().eq(Order::getOrderNo, orderNo));
        return order != null ? order.getId() : null;
    }

    // ---------- 内部工具 ----------

    private Order requireOwnedOrder(Long userId, Long orderId) {
        Order order = orderMapper.selectById(orderId);
        if (order == null || !order.getUserId().equals(userId)) {
            throw new BizException(TradeErrorCode.ORDER_NOT_FOUND, "订单不存在");
        }
        return order;
    }

    private String generateOrderNo() {
        String prefix = LocalDateTime.now().format(ORDER_NO_FMT);
        int random = new Random().nextInt(900000) + 100000;
        return prefix + random;
    }

    private String buildReceiverAddress(AddressDTO addr) {
        StringBuilder sb = new StringBuilder();
        if (addr.getProvince() != null) sb.append(addr.getProvince());
        if (addr.getCity() != null)     sb.append(addr.getCity());
        if (addr.getDistrict() != null) sb.append(addr.getDistrict());
        if (addr.getDetail() != null)   sb.append(addr.getDetail());
        return sb.toString();
    }

    private String formatSkuProperties(ProductSkuDTO sku) {
        if (sku == null || sku.getProperties() == null || sku.getProperties().isEmpty()) {
            return null;
        }
        return sku.getProperties().entrySet().stream()
                .map(e -> e.getKey() + ": " + e.getValue())
                .collect(Collectors.joining(" / "));
    }

    private AddressDTO fetchAddress(Long addressId) {
        if (addressId == null) return null;
        try {
            Result<AddressDTO> resp = userClient.getAddress(addressId);
            if (resp != null && resp.isSuccess()) {
                return resp.getData();
            }
        } catch (Exception e) {
            log.warn("[order] fetch address via Feign failed: {}", e.getMessage());
        }
        return null;
    }

    private Map<Long, ProductDTO> fetchProducts(List<Long> ids) {
        if (ids.isEmpty()) return new HashMap<>();
        try {
            Result<List<ProductDTO>> resp = productClient.batch(ids);
            if (resp != null && resp.isSuccess() && resp.getData() != null) {
                return resp.getData().stream()
                        .collect(Collectors.toMap(ProductDTO::getId, p -> p));
            }
        } catch (Exception e) {
            log.warn("[order] fetch products via Feign failed: {}", e.getMessage());
        }
        return new HashMap<>();
    }

    private Map<Long, ProductSkuDTO> fetchSkus(List<Long> ids) {
        if (ids.isEmpty()) return new HashMap<>();
        try {
            Result<List<ProductSkuDTO>> resp = productClient.skuBatch(ids);
            if (resp != null && resp.isSuccess() && resp.getData() != null) {
                return resp.getData().stream()
                        .collect(Collectors.toMap(ProductSkuDTO::getId, s -> s));
            }
        } catch (Exception e) {
            log.warn("[order] fetch skus via Feign failed: {}", e.getMessage());
        }
        return new HashMap<>();
    }
}

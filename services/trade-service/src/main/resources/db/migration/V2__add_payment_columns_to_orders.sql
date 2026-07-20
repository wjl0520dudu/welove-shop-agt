-- =====================================================================
-- V2: 支付宝沙箱支付接入 — orders 表加支付渠道与支付宝交易号
-- schema: trade_svc
-- 字段:
--   pay_channel: 支付渠道,默认 'MOCK'(模拟),接沙箱后为 'ALIPAY_SANDBOX'
--   trade_no:    支付宝交易号(异步通知里拿到,TRADE_SUCCESS 之后写)
-- 索引: trade_no 用部分唯一索引(允许 NULL 重复,非 NULL 必须唯一)
-- =====================================================================

SET search_path TO trade_svc;

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS pay_channel VARCHAR(20) NOT NULL DEFAULT 'MOCK',
    ADD COLUMN IF NOT EXISTS trade_no    VARCHAR(64);

COMMENT ON COLUMN orders.pay_channel IS '支付渠道: MOCK(模拟) / ALIPAY_SANDBOX(支付宝沙箱) / 未来加 WECHAT/ALIPAY_PROD 等';
COMMENT ON COLUMN orders.trade_no    IS '支付宝交易号(异步通知里回传,TRADE_SUCCESS 后写入)';

-- 部分唯一索引:trade_no 允许 NULL(未支付订单),非 NULL 必须全局唯一,防重复入账
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_trade_no
    ON orders(trade_no)
    WHERE trade_no IS NOT NULL;

# 生产配置集中管理

服务器的配置唯一来源是两个文件：

```text
/opt/welove-shop/config/production.env             # 可公开的运行参数
/opt/welove-shop/secrets/production.secrets.env    # 密钥，权限 600
```

对应模板为 `deploy/config/production.env.example` 和 `deploy/secrets/production.secrets.env.example`。GitHub Actions 只读取 SSH 凭据；不会上传或覆盖这两个文件。每次发布只会修改 `config/production.env` 的 `IMAGE_TAG`。

## 配置归属

| 类型 | 位置 | 示例 |
|---|---|---|
| 密钥 | `production.secrets.env` | 数据库密码、JWT、Zilliz token、DashScope key |
| 容器网络/部署参数 | `production.env` | 域名、镜像 tag、`postgres`、`nacos`、`gateway` 地址 |
| AI 检索策略 | `production.env`；稳定后可迁 Nacos | collection、分块、rerank 候选数 |
| Java 动态业务参数 | Nacos（非敏感） | 缓存 TTL、限流、日志级别、功能开关 |
| 前端 API 地址 | 不配置 | 两个 H5 均访问同源 `/api`，由外层 Nginx 转给 Gateway |
| 前端图片域名 | `production.env` | `IMAGE_BASE_URL` 由容器启动时生成公开的 `runtime-config.js` |

Nacos 不能存密码、Token、JWT 或云厂商密钥；这些只放服务器 secrets 文件。修改任一 env 文件后，执行：

```bash
cd /opt/welove-shop
docker compose --env-file config/production.env --env-file secrets/production.secrets.env -f docker-compose.prod.yml up -d
```

## 用户端 HTTPS

`SHOP_DOMAIN` 必须先通过 A 记录解析到生产服务器，安全组开放 TCP `80/443`。首次启动 HTTPS Nginx 前，使用 Certbot standalone 模式生成证书：

```bash
mkdir -p /opt/welove-shop/certbot/conf /opt/welove-shop/certbot/www
docker run --rm -p 80:80 \
  -v /opt/welove-shop/certbot/conf:/etc/letsencrypt \
  -v /opt/welove-shop/certbot/www:/var/www/certbot \
  certbot/certbot:latest certonly --standalone --non-interactive \
  --agree-tos --no-eff-email --email "$CERTBOT_EMAIL" -d "$SHOP_DOMAIN"
```

证书位于 `/opt/welove-shop/certbot/conf/live/$SHOP_DOMAIN/`，由 Nginx 只读挂载。当前管理端域名仍使用 HTTP；只有在 `ADMIN_DOMAIN` 完成 DNS 解析并签发对应证书后才能启用管理端 HTTPS。

证书续期使用仓库中的 `deploy/renew-certificates.sh`。部署时将脚本安装到 `/opt/welove-shop/scripts/renew-certificates.sh`，并配置每天自动检查：

```bash
mkdir -p /opt/welove-shop/scripts /opt/welove-shop/logs
install -m 0755 deploy/renew-certificates.sh /opt/welove-shop/scripts/renew-certificates.sh
(crontab -l 2>/dev/null; echo '17 3 * * * /opt/welove-shop/scripts/renew-certificates.sh >> /opt/welove-shop/logs/certbot-renew.log 2>&1') | crontab -
```

Certbot 每天检查但只在证书进入续期窗口时签发新证书。脚本会在续期检查后先执行 `nginx -t`，通过后再热重载 Nginx。首次配置或修改续期逻辑后必须执行模拟续期：

```bash
/opt/welove-shop/scripts/renew-certificates.sh --dry-run
```

定期检查 `/opt/welove-shop/logs/certbot-renew.log`，并在外部监控证书剩余有效期；仅配置 cron 不能覆盖服务器宕机、Docker 故障或 CA 请求失败等情况。

## 聊天图片对象存储

聊天图片必须上传到 AI 服务与 DashScope 都能访问的公开 URL；容器本地磁盘地址不能用于多模态检索。在服务器的
`secrets/production.secrets.env` 中填写：

```dotenv
CLOUD_STORAGE_ACCESS_KEY=<阿里云 RAM AccessKeyId>
CLOUD_STORAGE_SECRET_KEY=<阿里云 RAM AccessKeySecret>
CLOUD_STORAGE_BUCKET=<OSS Bucket 名称>
CLOUD_STORAGE_DOMAIN=https://<Bucket 公共访问域名或 CDN 域名>
```

在 `config/production.env` 中填写 Bucket 所在地域的非敏感 endpoint，例如杭州：

```dotenv
CLOUD_STORAGE_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
```

RAM 凭证至少需要该 Bucket 的 `PutObject` 权限；`CLOUD_STORAGE_DOMAIN` 必须可从公网 HTTPS 访问。它用于聊天上传，和商品图片的 `IMAGE_BASE_URL` 是两项不同配置。聊天文件会写入 `weloveshop/chat/`，不会再与知识库文档混在同一前缀。

## 前端的特殊点

商城与管理端的 API 都是相对路径，因此域名变化无需重建前端镜像。商品图片域名由前端容器启动时生成 `/runtime-config.js`；修改服务器 `IMAGE_BASE_URL` 后执行一次 Compose 更新即可生效，不需要重新构建前端镜像。该文件会被浏览器下载，因此只能包含公开配置，严禁写入 token 或任何密钥。

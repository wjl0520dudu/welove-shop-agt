package com.demo.weloveShopSystem.common;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.SignatureAlgorithm;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.security.Key;
import java.util.Date;
import java.util.Map;

/**
 * JWT 工具类，负责生成、解析和校验访问令牌与刷新令牌。
 */
@Component
public class JwtUtil {

    /** JWT 签名密钥。 */
    @Value("${jwt.secret}")
    private String secret;

    /** 访问令牌过期时间，单位毫秒。 */
    @Value("${jwt.expiration:3600000}")
    private long expiration;

    /** 刷新令牌过期时间，单位毫秒。 */
    @Value("${jwt.refresh-expiration:86400000}")
    private long refreshExpiration;

    /**
     * 根据配置的密钥生成 JWT 签名 Key。
     */
    private Key getSigningKey() {
        byte[] keyBytes = secret.getBytes();
        return Keys.hmacShaKeyFor(keyBytes);
    }

    /**
     * 生成访问令牌。
     *
     * @param subject token 主体，通常是用户标识
     * @param claims  业务声明，例如 userId、role
     * @return JWT 字符串
     */
    public String generateToken(String subject, Map<String, Object> claims) {
        Date now = new Date();
        Date expiryDate = new Date(now.getTime() + expiration);

        return Jwts.builder()
                .setClaims(claims)
                .setSubject(subject)
                .setIssuedAt(now)
                .setExpiration(expiryDate)
                .signWith(getSigningKey(), SignatureAlgorithm.HS256)
                .compact();
    }

    /**
     * 生成刷新令牌。
     *
     * @param subject token 主体，通常是用户标识
     * @return JWT 字符串
     */
    public String generateRefreshToken(String subject) {
        Date now = new Date();
        Date expiryDate = new Date(now.getTime() + refreshExpiration);

        return Jwts.builder()
                .setSubject(subject)
                .setIssuedAt(now)
                .setExpiration(expiryDate)
                .signWith(getSigningKey(), SignatureAlgorithm.HS256)
                .compact();
    }

    /**
     * 解析 JWT 并返回声明内容。
     */
    public Claims parseToken(String token) {
        return Jwts.parserBuilder()
                .setSigningKey(getSigningKey())
                .build()
                .parseClaimsJws(token)
                .getBody();
    }

    /**
     * 校验 JWT 是否合法且未过期。
     */
    public boolean validateToken(String token) {
        try {
            Jwts.parserBuilder()
                    .setSigningKey(getSigningKey())
                    .build()
                    .parseClaimsJws(token);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * 获取 token 主体。
     */
    public String getSubject(String token) {
        return parseToken(token).getSubject();
    }

    /**
     * 获取 token 过期时间。
     */
    public Date getExpiration(String token) {
        return parseToken(token).getExpiration();
    }
}

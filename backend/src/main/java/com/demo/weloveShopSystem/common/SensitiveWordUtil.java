package com.demo.weloveShopSystem.common;

import cn.hutool.dfa.WordTree;
import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.List;

/**
 * 敏感词检测与过滤工具。
 * <p>
 * 内部使用 Hutool 的 DFA WordTree 做多模式匹配,常见接入点是用户名注册/更新、
 * 商品评价、聊天问题预校验等需要过滤违规词的场景。
 * <p>
 * 当前词表是内置示例,后续可以改为在启动时从数据库、配置中心或独立文本文件加载,
 * 命中判断与替换实现保持不变。
 */
@Component
public class SensitiveWordUtil {

    /** DFA 敏感词匹配树,单例复用,PostConstruct 阶段一次性构建。 */
    private final WordTree wordTree = new WordTree();

    /** 初始化默认敏感词库。 */
    @PostConstruct
    public void init() {
        List<String> sensitiveWords = Arrays.asList("暴力", "色情", "赌博", "admin", "root", "system");
        wordTree.addWords(sensitiveWords);
    }

    /**
     * 判断给定文本是否包含任意敏感词。
     *
     * @param text 待检测文本,null 直接返回 false
     */
    public boolean contains(String text) {
        if (text == null) {
            return false;
        }
        return wordTree.isMatch(text);
    }

    /**
     * 将文本中命中的所有敏感词替换为等长星号,不改变整体文本长度。
     * <p>
     * distinct 是为了避免同一敏感词多次触发 replace 造成的重复扫描。
     *
     * @param text 待过滤文本,null 时直接返回 null
     * @return 过滤后的字符串
     */
    public String filter(String text) {
        if (text == null) {
            return null;
        }
        return wordTree.matchAll(text).stream()
                .distinct()
                .reduce(text, (acc, word) -> acc.replace(word, "*".repeat(word.length())));
    }
}

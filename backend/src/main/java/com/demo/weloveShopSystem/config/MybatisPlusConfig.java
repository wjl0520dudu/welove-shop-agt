package com.demo.weloveShopSystem.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * MyBatis-Plus 配置。
 * <p>
 * 目前只挂分页插件,DbType 与项目主库保持一致(MySQL);
 * 后续需要乐观锁、防全表更新等内建拦截器,可以在这里追加 addInnerInterceptor。
 */
@Configuration
public class MybatisPlusConfig {

    /** 注册 MyBatis-Plus 插件链,当前只包含分页插件。 */
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}

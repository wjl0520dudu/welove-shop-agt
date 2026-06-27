package com.demo.weloveShopSystem;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableAsync
@EnableScheduling
@MapperScan("com.demo.weloveShopSystem.mapper")
public class weloveShopSystemApplication {

    public static void main(String[] args) {
        SpringApplication.run(weloveShopSystemApplication.class, args);
    }

}

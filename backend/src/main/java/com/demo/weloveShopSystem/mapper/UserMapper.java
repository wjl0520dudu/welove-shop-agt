package com.demo.weloveShopSystem.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import com.demo.weloveShopSystem.entity.User;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface UserMapper extends BaseMapper<User> {
}

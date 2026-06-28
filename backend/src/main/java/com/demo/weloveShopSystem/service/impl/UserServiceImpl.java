package com.demo.weloveShopSystem.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.demo.weloveShopSystem.entity.User;
import com.demo.weloveShopSystem.mapper.UserMapper;
import com.demo.weloveShopSystem.service.UserService;
import org.springframework.stereotype.Service;

@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {

    @Override
    public void updateStatus(Long userId, Integer status) {
        User user = this.getById(userId);
        if (user != null) {
            user.setStatus(status);
            this.updateById(user);
        }
    }
}

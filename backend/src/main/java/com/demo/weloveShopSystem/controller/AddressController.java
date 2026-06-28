package com.demo.weloveShopSystem.controller;



import com.demo.weloveShopSystem.common.Result;
import com.demo.weloveShopSystem.entity.Address;
import com.demo.weloveShopSystem.service.AddressService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 用户收货地址控制器。
 */
@RestController
@RequestMapping("/api/address")
@RequiredArgsConstructor
public class AddressController {

    private final AddressService addressService;

    /** 从 Spring Security 上下文获取当前登录用户 ID。 */
    private Long getCurrentUserId() {
        return Long.parseLong(SecurityContextHolder.getContext().getAuthentication().getName());
    }

    /** 查询当前用户的收货地址列表。 */
    @GetMapping("/list")
    public Result<List<Address>> list() {
        return Result.success(addressService.listByUserId(getCurrentUserId()));
    }

    /** 新增当前用户的收货地址。 */
    @PostMapping("/add")
    public Result<Address> add(@RequestBody Address address) {
        address.setUserId(getCurrentUserId());
        return Result.success(addressService.addAddress(address));
    }

    /** 更新当前用户的收货地址。 */
    @PutMapping("/update")
    public Result<Address> update(@RequestBody Address address) {
        address.setUserId(getCurrentUserId());
        return Result.success(addressService.updateAddress(address));
    }

    /** 删除当前用户的指定收货地址。 */
    @DeleteMapping("/delete")
    public Result<Void> delete(@RequestParam Long id) {
        addressService.deleteAddress(id, getCurrentUserId());
        return Result.success(null);
    }

    /** 设置当前用户的默认收货地址。 */
    @PutMapping("/setDefault")
    public Result<Void> setDefault(@RequestParam Long id) {
        addressService.setDefault(id, getCurrentUserId());
        return Result.success(null);
    }
}

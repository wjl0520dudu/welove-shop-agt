package com.demo.weloveShopSystem.service;

import com.demo.weloveShopSystem.entity.Address;
import java.util.List;

/**
 * 收货地址服务接口。
 */
public interface AddressService {
    /** 查询用户的收货地址列表。 */
    List<Address> listByUserId(Long userId);
    /** 新增收货地址。 */
    Address addAddress(Address address);
    /** 更新收货地址。 */
    Address updateAddress(Address address);
    /** 删除指定用户的收货地址。 */
    void deleteAddress(Long id, Long userId);
    /** 将指定地址设置为默认地址。 */
    void setDefault(Long id, Long userId);
}

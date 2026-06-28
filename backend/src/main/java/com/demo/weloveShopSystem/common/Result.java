package com.demo.weloveShopSystem.common;

import lombok.Data;

/**
 * 统一接口响应结构。
 *
 * @param <T> 响应数据类型
 */
@Data
public class Result<T> {
    /** 业务状态码，200 表示成功。 */
    private Integer code;
    /** 响应提示信息。 */
    private String message;
    /** 响应数据。 */
    private T data;

    /**
     * 构造成功响应。
     */
    public static <T> Result<T> success(T data) {
        Result<T> result = new Result<>();
        result.setCode(200);
        result.setMessage("Success");
        result.setData(data);
        return result;
    }

    /**
     * 构造默认错误响应。
     */
    public static <T> Result<T> error(String message) {
        Result<T> result = new Result<>();
        result.setCode(500);
        result.setMessage(message);
        return result;
    }

    /**
     * 构造指定错误码的错误响应。
     */
    public static <T> Result<T> error(Integer code, String message) {
        Result<T> result = new Result<>();
        result.setCode(code);
        result.setMessage(message);
        return result;
    }
}

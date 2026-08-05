# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : errors.py
# @Description : 分销订单业务异常
"""


class DistributionOrderError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(msg)


class QianyiErpError(DistributionOrderError):
    """千易 Open API 调用或参数组装失败。"""

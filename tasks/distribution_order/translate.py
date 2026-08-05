# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : translate.py
# @Description : 翻译装饰器 stub（合入主仓后改 import 路径）
"""
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple
from apps.system.reports.view.common_func import get_translaiton_dict_from_request, translate_all_output


def translate_text(
    text: Optional[str], is_trans: bool, translation_dict: dict
) -> Optional[str]:
    if text is None:
        return None
    if is_trans:
        return translation_dict.get(text, text)
    return text

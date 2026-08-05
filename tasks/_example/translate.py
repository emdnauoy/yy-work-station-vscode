"""翻译工具（占位 stub）。

主仓真身：apps.system.reports.view.common_func
- translate_all_output：装饰器，自动翻译返回值
- get_translaiton_dict_from_request：散点翻译时手动取字典
复制任务后将 import 路径改回主仓。
"""
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple


def translate_all_output(
    modules: Optional[List[str]] = None,
    translatable_fields: Optional[List[str]] = None,
    kv_fields: Optional[List[str]] = None,
    v_fields: Optional[List[str]] = None,
    k_fields: Optional[List[str]] = None,
    skip_fields: Optional[List[str]] = None,
    default_lang: str = "cn",
) -> Callable:
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await fn(*args, **kwargs)

        return wrapper

    return deco


def get_translaiton_dict_from_request(
    request: Any, modules: List[str]
) -> Tuple[bool, Dict[str, Any]]:
    return False, {}

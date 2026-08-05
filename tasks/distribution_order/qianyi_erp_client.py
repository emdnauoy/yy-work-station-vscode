# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/2
# @Author  : Zhu Yaming
# @File    : qianyi_erp_client.py
# @Description : 千易 ERP Open API 客户端（签名、multipart 请求、订单创建）
"""
from __future__ import annotations

import hashlib
import io
import json
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from conf.settings import settings

from apps.system.distribution_order.errors import QianyiErpError

SERVICE_CREATE_SALES_ORDER = "CREATE_SALES_ORDER"
API_PATH_SALES_ORDER = "salesOrder"


def _normalize_scheme(url: str) -> str:
    """配置可只写域名；缺 scheme 时补 https://。"""
    url = url.strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url.lstrip("/")
    return url


def _resolve_base_url(base_url: str, version: str) -> str:
    """QIANYI_API_BASE_URL + QIANYI_API_VERSION → https://{host}/api/v1"""
    url = _normalize_scheme(base_url or "")
    if not url:
        return ""
    if "/api/" in url:
        return url
    ver = (version or "v1").strip().lstrip("/")
    return "%s/api/%s" % (url, ver)


def generate_sign(
    app_id: str, biz_param: str, service_type: str, timestamp: int, app_secret: str,
) -> str:
    """千易 Open API 签名：appId/bizParam/serviceType/timestamp 升序拼接 + appSecret，MD5 小写。"""
    sign_str = (
        "appId=%sbizParam=%sserviceType=%stimestamp=%s%s"
        % (app_id, biz_param, service_type, timestamp, app_secret)
    )
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()


def dumps_biz_param(biz_param: Dict[str, Any]) -> str:
    """bizParam JSON：紧凑格式，与千易签名字符串一致。"""
    return json.dumps(biz_param, ensure_ascii=False, separators=(",", ":"), default=str)


def _encode_multipart_form(fields: Dict[str, str]) -> Tuple[bytes, str]:
    boundary = "----QianyiFormBoundary%s" % secrets.token_hex(8)
    buf = io.BytesIO()
    for name, value in fields.items():
        buf.write(("--%s\r\n" % boundary).encode("utf-8"))
        buf.write(
            ('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode("utf-8")
        )
        buf.write(str(value).encode("utf-8"))
        buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % boundary).encode("utf-8"))
    return buf.getvalue(), boundary


@dataclass(frozen=True)
class QianyiErpConfig:
    app_id: str
    app_secret: str
    base_url: str
    timeout_sec: int = 60

    @classmethod
    def from_settings(cls, timeout_sec: int = 60) -> "QianyiErpConfig":
        app_id = (getattr(settings, "QIANYI_API_APP_ID", None) or "").strip()
        app_secret = (getattr(settings, "QIANYI_API_SECRET_KEY", None) or "").strip()
        base_url = _resolve_base_url(
            getattr(settings, "QIANYI_API_BASE_URL", None) or "",
            getattr(settings, "QIANYI_API_VERSION", None) or "v1",
        )
        if not app_id or not app_secret:
            raise QianyiErpError(
                40000,
                "缺少千易凭证：请在 settings 配置 QIANYI_API_APP_ID / QIANYI_API_SECRET_KEY",
            )
        if not base_url:
            raise QianyiErpError(
                40000,
                "缺少千易地址：请在 settings 配置 QIANYI_API_BASE_URL / QIANYI_API_VERSION",
            )
        return cls(app_id=app_id, app_secret=app_secret, base_url=base_url, timeout_sec=timeout_sec)


class QianyiErpClient:
    """千易 ERP Open API 同步 HTTP 客户端（下发场景可在 asyncio.to_thread 中调用）。"""

    def __init__(self, config: Optional[QianyiErpConfig] = None):
        self.config = config or QianyiErpConfig.from_settings()

    def _post_form(self, api_path: str, service_type: str, biz_param: Dict[str, Any]) -> Dict[str, Any]:
        biz_param_str = dumps_biz_param(biz_param)
        timestamp = int(time.time() * 1000)
        sign = generate_sign(
            self.config.app_id, biz_param_str, service_type, timestamp, self.config.app_secret,
        )
        form_fields = {
            "appId": self.config.app_id,
            "serviceType": service_type,
            "bizParam": biz_param_str,
            "timestamp": str(timestamp),
            "sign": sign,
        }
        body, boundary = _encode_multipart_form(form_fields)
        url = "%s/%s" % (self.config.base_url, api_path.lstrip("/"))
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise QianyiErpError(40000, "千易 HTTP %s: %s" % (exc.code, raw)) from exc
        except urllib.error.URLError as exc:
            raise QianyiErpError(40000, "千易网络异常: %s" % exc.reason) from exc
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise QianyiErpError(40000, "千易响应非 JSON: %s" % raw[:500]) from exc
        return self._parse_api_response(payload)

    @staticmethod
    def _parse_api_response(payload: Dict[str, Any]) -> Dict[str, Any]:
        state = (payload.get("state") or "").strip().lower()
        error_code = payload.get("errorCode") or ""
        error_msg = payload.get("errorMsg") or ""
        if state != "success":
            msg = error_msg or error_code or "千易请求失败"
            raise QianyiErpError(40000, msg)
        biz_content_raw = payload.get("bizContent")
        biz_content: Dict[str, Any] = {}
        if biz_content_raw:
            try:
                biz_content = json.loads(biz_content_raw)
            except (TypeError, ValueError):
                biz_content = {"raw": biz_content_raw}
        inner_state = (biz_content.get("state") or "").strip().lower()
        if biz_content.get("notSuccess") or (inner_state and inner_state != "success"):
            inner_msg = biz_content.get("errorMsg") or biz_content.get("errorCode") or error_msg
            raise QianyiErpError(40000, inner_msg or "千易业务失败")
        result = biz_content.get("result") or biz_content
        return {
            "request_id": payload.get("requestId"),
            "order_number": result.get("orderNumber") if isinstance(result, dict) else None,
            "online_order_number": result.get("onlineOrderNumber") if isinstance(result, dict) else None,
            "result": result,
            "raw": payload,
        }

    def create_sales_order(self, biz_param: Dict[str, Any]) -> Dict[str, Any]:
        """调用 CREATE_SALES_ORDER 创建销售订单。"""
        return self._post_form(API_PATH_SALES_ORDER, SERVICE_CREATE_SALES_ORDER, biz_param)

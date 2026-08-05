import json
import os
import sys
import time
import uuid

_TASK_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _TASK_ROOT)

import importlib.util
import types

def _ensure(name):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]

root = _ensure("apps")
sys_pkg = _ensure("apps.system")
pkg = _ensure("apps.system.distribution_order")
setattr(root, "system", sys_pkg)
setattr(sys_pkg, "distribution_order", pkg)

for mod_name, filename in (("errors", "errors.py"), ("qianyi_erp_client", "qianyi_erp_client.py")):
    path = "apps.system.distribution_order.%s" % mod_name
    spec = importlib.util.spec_from_file_location(path, os.path.join(_TASK_ROOT, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path] = mod
    spec.loader.exec_module(mod)
    setattr(pkg, mod_name, mod)

from apps.system.distribution_order.qianyi_erp_client import (
    QianyiErpClient, QianyiErpConfig, QIANYI_ERP_HOST_TEST, dumps_biz_param, generate_sign,
)
import urllib.request
import urllib.error
from apps.system.distribution_order.qianyi_erp_client import _encode_multipart_form

APP_ID = "1768892099208-134"
APP_SECRET = "5f66f296ade9c6b0cecb6225b17b7b5e"

config = QianyiErpConfig(app_id=APP_ID, app_secret=APP_SECRET, host="www.qianyierp.com")
online_sn = "WS-TEST-%s" % uuid.uuid4().hex[:12].upper()
biz = {
    "shop": "Solaso-ERP",
    "onlineOrderNumber": online_sn,
    "trackingNumber": online_sn,
    "paymentMethod": "COD",
    "codPayAmount": 100000,
    "currency": "IDR",
    "payTime": "2024-05-20 15:40:30+08:00",
    "buyer": {
        "receiverName": "Test User",
        "country": "ID",
        "address1": "Plaza 89 Rasuna Said",
        "postCode": "12940",
    },
    "skuList": [{"sku": "DP001", "payAmount": 0, "quantity": 1}],
}
biz_str = dumps_biz_param(biz)
ts = int(time.time() * 1000)
sign = generate_sign(APP_ID, biz_str, "CREATE_SALES_ORDER", ts, APP_SECRET)
fields = {
    "appId": APP_ID,
    "serviceType": "CREATE_SALES_ORDER",
    "bizParam": biz_str,
    "timestamp": str(ts),
    "sign": sign,
}
body, boundary = _encode_multipart_form(fields)
url = config.base_url + "/salesOrder"
req = urllib.request.Request(url, data=body, method="POST", headers={
    "Content-Type": "multipart/form-data; boundary=%s" % boundary,
})
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
except urllib.error.HTTPError as e:
    raw = e.read().decode("utf-8", errors="replace")
    print("HTTP", e.code)
print(raw)

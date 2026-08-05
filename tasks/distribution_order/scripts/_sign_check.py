import hashlib
biz = (
    '{"asnSkuVOList":[{"expectQuantity":"100","sku":"SKU1230"}],'
    '"warehouseName":"测试仓库"}'
)
s = (
    "appId=openApi_TESTbizParam=%sserviceType=CREATE_ASN_ORDERtimestamp=1662448537275openApi_TOKEN"
    % biz
)
print(hashlib.md5(s.encode("utf-8")).hexdigest())

# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : auth.py
# @Description : 鉴权依赖（合入主仓后改 import 路径）
"""
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login/")

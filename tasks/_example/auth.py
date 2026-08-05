"""鉴权依赖（占位 stub）。

主仓真身：oauth2_scheme = OAuth2PasswordBearer(tokenUrl=settings.AuthUrlPart + "/login/")
复制任务后将 import 路径改回主仓提供的实例。
"""
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login/")

"""登录密码加密：AES-CBC，密钥与 IV 均为超星前端硬编码的 ``u2oh6Vu^HWe4_AES``。

超星 passport2 的 ``fanyalogin`` 端点要求用户名和密码都经过该加密后以 Base64 提交。
"""

from __future__ import annotations

import base64

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

AES_KEY = "u2oh6Vu^HWe4_AES"


def encrypt(plaintext: str) -> str:
    """AES-CBC + PKCS7 填充，输出 Base64。"""
    cipher = AES.new(AES_KEY.encode("utf-8"), AES.MODE_CBC, AES_KEY.encode("utf-8"))
    ciphertext = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(ciphertext).decode("utf-8")


def decrypt(ciphertext_b64: str) -> str:
    """解密（主要用于测试与调试）。"""
    cipher = AES.new(AES_KEY.encode("utf-8"), AES.MODE_CBC, AES_KEY.encode("utf-8"))
    return unpad(cipher.decrypt(base64.b64decode(ciphertext_b64)), AES.block_size).decode("utf-8")

"""登录加密测试：验证与超星前端一致的 AES-CBC 行为。"""

import base64

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from cxauto.api import cipher


def test_encrypt_roundtrip():
    """密文可用相同密钥/IV 解密还原。"""
    plaintext = "13800138000"
    raw = base64.b64decode(cipher.encrypt(plaintext))
    aes = AES.new(cipher.AES_KEY.encode(), AES.MODE_CBC, cipher.AES_KEY.encode())
    assert unpad(aes.decrypt(raw), AES.block_size).decode() == plaintext


def test_encrypt_output_is_base64_and_block_aligned():
    ciphertext = cipher.encrypt("password123")
    raw = base64.b64decode(ciphertext)  # 不是合法 base64 会抛异常
    assert len(raw) % AES.block_size == 0
    assert ciphertext != "password123"


def test_encrypt_chinese():
    assert cipher.decrypt(cipher.encrypt("测试中文")) == "测试中文"

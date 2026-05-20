"""
Replica la encriptacion AES del frontend (CryptoJS + btoa).
El frontend usa CryptoJS.AES.encrypt con derivacion EVP_BytesToKey (MD5)
en modo CBC con PKCS7 padding. Luego aplica btoa() al resultado base64.
"""

import base64
import hashlib
import json
import struct

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.Random import get_random_bytes

# Clave hardcodeada usada por z7() para el endpoint de token
HARDCODED_KEY = "z427FcQwMSPZuFbIjNWGDqUpw1MEo1DG7cIOBSuI3ps"

# Prefijo OpenSSL que CryptoJS usa para indicar salted encryption
SALTED_PREFIX = b"Salted__"
SALT_SIZE = 8
KEY_SIZE = 32  # AES-256
IV_SIZE = 16
MD5_ITERATIONS = 1


def _evp_bytes_to_key(password: str, salt: bytes) -> tuple[bytes, bytes]:
    """
    Deriva clave AES + IV a partir de password usando EVP_BytesToKey con MD5.
    Replica el comportamiento de CryptoJS cuando se usa un string como key.
    """
    password_bytes = password.encode("utf-8")
    derived = b""
    block = b""

    while len(derived) < KEY_SIZE + IV_SIZE:
        md5 = hashlib.md5()
        md5.update(block)
        md5.update(password_bytes)
        md5.update(salt)
        block = md5.digest()
        derived += block

    key = derived[:KEY_SIZE]
    iv = derived[KEY_SIZE : KEY_SIZE + IV_SIZE]
    return key, iv


def crypto_aes_encrypt(plaintext: str, key: str) -> str:
    """
    Replica sx.AES.encrypt(plaintext, key).toString() de CryptoJS.
    Devuelve el ciphertext en formato base64 OpenSSL (con prefijo Salted__).
    """
    salt = get_random_bytes(SALT_SIZE)
    aes_key, iv = _evp_bytes_to_key(key, salt)

    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    plaintext_bytes = plaintext.encode("utf-8")
    padded = pad(plaintext_bytes, AES.block_size)
    ciphertext = cipher.encrypt(padded)

    # Formato: Salted__ + salt + ciphertext
    salted_ciphertext = SALTED_PREFIX + salt + ciphertext
    return base64.b64encode(salted_ciphertext).decode("utf-8")


def encrypt_api_payload(action: str, data: object, key: str) -> str:
    """
    Replica la funcion $o(t, e, n) del frontend.
    Construye el payload JSON, lo encripta con AES usando key como password,
    y lo codifica con btoa (base64 del base64).
    """
    from datetime import datetime

    now = datetime.now()
    fecha = f"{now.weekday()}-{now.month}-{now.year}"

    payload = {
        "fecha": fecha,
        "accion": action,
        "data": data,
    }
    json_str = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    # Paso 1: AES encrypt (CryptoJS format, ya en base64)
    step1 = crypto_aes_encrypt(json_str, key)
    # Paso 2: btoa() = base64 del string base64
    step2 = base64.b64encode(step1.encode("utf-8")).decode("utf-8")
    return step2


def encrypt_token() -> str:
    """
    Replica z7('token', null) del frontend para obtener el
    parametro encriptado del endpoint de token.
    """
    from datetime import datetime

    now = datetime.now()
    fecha = f"{now.weekday()}-{now.month}-{now.year}"

    payload = {
        "fecha": fecha,
        "accion": "token",
        "data": None,
    }
    json_str = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    step1 = crypto_aes_encrypt(json_str, HARDCODED_KEY)
    step2 = base64.b64encode(step1.encode("utf-8")).decode("utf-8")
    return step2

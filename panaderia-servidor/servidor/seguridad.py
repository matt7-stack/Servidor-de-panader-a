"""Contraseñas (scrypt, solo librería estándar) y límite de intentos de acceso."""
import base64
import hashlib
import hmac
import os
import time

_FALSO = None


def hashear(clave: str) -> str:
    sal = os.urandom(16)
    n, r, p = 2 ** 14, 8, 1
    h = hashlib.scrypt(clave.encode(), salt=sal, n=n, r=r, p=p, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (n, r, p, base64.b64encode(sal).decode(), base64.b64encode(h).decode())


def verificar(clave: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calc = hashlib.scrypt(clave.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def hash_falso() -> str:
    """Se usa cuando el usuario no existe, para que la respuesta tarde lo mismo."""
    global _FALSO
    if _FALSO is None:
        _FALSO = hashear("no-existe-este-usuario")
    return _FALSO


def clave_valida(clave) -> bool:
    return isinstance(clave, str) and len(clave) >= 10


class Limitador:
    """Bloquea un usuario desde una IP tras varios fallos seguidos.
    Vive en memoria: se reinicia con el servidor y no se comparte entre procesos."""

    def __init__(self, maximo=5, bloqueo=900):
        self.maximo, self.bloqueo, self.fallos = maximo, bloqueo, {}

    def bloqueado(self, k) -> bool:
        return time.time() < self.fallos.get(k, (0, 0))[1]

    def fallo(self, k):
        c = self.fallos.get(k, (0, 0))[0] + 1
        self.fallos[k] = (c, time.time() + self.bloqueo if c >= self.maximo else 0)

    def ok(self, k):
        self.fallos.pop(k, None)

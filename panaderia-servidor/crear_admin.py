"""Crea el primer administrador desde la terminal:  python crear_admin.py"""
import getpass
import os
import re

from servidor import seguridad as seg
from servidor.bd import BD
from servidor.datos import ahora, auditar


def main():
    bd = BD(os.environ.get("DATABASE_URL", "sqlite:///panaderia.db"))
    usuario = input("Usuario del administrador: ").strip().lower()
    if not re.match(r"^[a-z0-9._-]{3,30}$", usuario):
        raise SystemExit("Usuario inválido (3 a 30 caracteres: minúsculas, números, punto o guion).")
    clave = getpass.getpass("Contraseña (mínimo 10 caracteres): ")
    if not seg.clave_valida(clave) or clave != getpass.getpass("Repite la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden o son demasiado cortas.")
    with bd.tx() as t:
        if t.una("SELECT 1 AS x FROM usuarios WHERE usuario=?", (usuario,)):
            raise SystemExit("Ese usuario ya existe.")
        uid = t.insertar("INSERT INTO usuarios(usuario,nombre,rol,clave,creado) VALUES(?,?,?,?,?)",
                         (usuario, "Administrador", "admin", seg.hashear(clave), ahora()))
        auditar(t, None, "crear_admin_inicial", "usuarios", uid)
    print("Administrador creado.")


if __name__ == "__main__":
    main()

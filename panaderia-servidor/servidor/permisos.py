"""Quién puede leer, crear, actualizar y borrar cada colección."""
ROLES = ("admin", "dueno", "panadero", "repartidor")

COLS = {"movs", "cats", "pagos", "provs", "ins", "comps", "sm", "emp", "pe", "pro",
        "pm", "pd", "dp", "od", "rc", "cj", "ajustes"}

LEER = {
    "admin": COLS,
    "dueno": COLS,
    "panadero": {"ins", "pro", "sm", "pm", "pd", "od", "dp", "cats", "pagos"},
    "repartidor": {"od", "dp"},
}

CREAR = {
    "admin": COLS,
    "dueno": {"movs"},
    "panadero": {"sm", "pm"},
    "repartidor": set(),
}

# Campos que cada rol puede modificar (None = todos). Quien no aparece, ninguno.
ACTUALIZAR = {
    "panadero": {"ins": {"st"}, "pro": {"st"}},
}

BORRAR = {"admin": COLS}

PEDIDOS = {"admin", "repartidor"}


def puede_leer(rol, col):
    return col in LEER.get(rol, ())


def puede_crear(rol, col, datos):
    if col not in CREAR.get(rol, ()):
        return False
    if rol == "dueno" and col == "movs":
        return datos.get("o", "manual") == "manual" and datos.get("t") in ("ingreso", "gasto")
    if rol == "panadero" and col == "sm":
        return datos.get("t") in ("consumo", "merma")
    return True


def campos_actualizables(rol, col):
    """None = todos los campos; un conjunto vacío = ninguno."""
    if rol == "admin":
        return None
    return ACTUALIZAR.get(rol, {}).get(col, set())


def puede_borrar(rol, col):
    return col in BORRAR.get(rol, ())


def puede_operar_pedidos(rol):
    return rol in PEDIDOS

"""Operaciones sobre los registros, siempre comprobando permisos, y acciones de pedidos."""
import json
import re
from datetime import datetime, timezone

from . import permisos as per


class Error(Exception):
    codigo = 400


class Denegado(Error):
    codigo = 403


class NoExiste(Error):
    codigo = 404


class Conflicto(Error):
    codigo = 409


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hoy(tz="America/Asuncion"):
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def nuevo_id(t, n=1):
    """Entrega n identificadores consecutivos y devuelve el primero. Todos los registros
    usan este contador, así nunca chocan los ids del servidor con los de cada dispositivo."""
    v = t.una("UPDATE contador SET valor=valor+? WHERE id=1 RETURNING valor", (n,))["valor"]
    return v - n + 1


def reservar(t, u, n):
    n = max(1, min(1000, int(n)))
    desde = nuevo_id(t, n)
    t.ejecutar("INSERT INTO bloques(usuario_id,desde,hasta) VALUES(?,?,?)", (u["id"], desde, desde + n - 1))
    return {"desde": desde, "cuantos": n}


def _crear_registro(t, rid, col, datos):
    t.ejecutar("INSERT INTO registros(id,coleccion,datos,ver) VALUES(?,?,?,1)", (rid, col, json.dumps(datos)))


def auditar(t, u, accion, col=None, rid=None, detalle=None):
    txt = json.dumps(detalle, ensure_ascii=False, default=str)[:2000] if detalle is not None else None
    t.ejecutar(
        "INSERT INTO auditoria(ts,usuario,rol,accion,coleccion,rid,detalle) VALUES(?,?,?,?,?,?,?)",
        (ahora(), (u or {}).get("usuario"), (u or {}).get("rol"), accion, col, rid, txt))


def _resolver(v, ids):
    """Reemplaza "$0", "$1"... por el id del registro creado en esa posición del lote."""
    if isinstance(v, str) and re.fullmatch(r"\$\d+", v):
        i = int(v[1:])
        if i >= len(ids):
            raise Error("Referencia inválida en el lote")
        return ids[i]
    if isinstance(v, dict):
        return {k: _resolver(x, ids) for k, x in v.items()}
    if isinstance(v, list):
        return [_resolver(x, ids) for x in v]
    return v


def _limpiar(d):
    if not isinstance(d, dict):
        raise Error("Los datos deben ser un objeto")
    d = {k: v for k, v in d.items() if k not in ("id", "ver")}
    if len(json.dumps(d)) > 20000:
        raise Error("Registro demasiado grande")
    return d


def _entero(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise Error("Identificador inválido")


def aplicar(t, u, ops):
    """Aplica una lista de operaciones. Si una falla, el llamador revierte todas."""
    rol, ids, res = u["rol"], [], []
    for op in ops:
        if not isinstance(op, dict):
            raise Error("Operación inválida")
        tipo, col = op.get("op"), op.get("col")
        if col not in per.COLS:
            raise Error("Colección desconocida")
        if tipo == "crear":
            datos = _limpiar(_resolver(op.get("datos"), ids))
            if not per.puede_crear(rol, col, datos):
                raise Denegado("No puedes crear registros en " + col)
            if "id" in op:
                rid = _entero(op["id"])
                if not t.una("SELECT 1 AS x FROM bloques WHERE usuario_id=? AND desde<=? AND hasta>=?", (u["id"], rid, rid)):
                    raise Denegado("Identificador no reservado para este usuario")
                if t.una("SELECT 1 AS x FROM registros WHERE id=?", (rid,)):
                    raise Conflicto("El identificador ya está en uso")
            else:
                rid = nuevo_id(t)
            _crear_registro(t, rid, col, datos)
            res.append({"id": rid, "ver": 1})
            auditar(t, u, "crear", col, rid, datos)
        elif tipo == "actualizar":
            rid = _entero(_resolver(op.get("id"), ids))
            cambios = _limpiar(_resolver(op.get("datos"), ids))
            permitidos = per.campos_actualizables(rol, col)
            if permitidos is not None and (not cambios or not set(cambios) <= permitidos):
                raise Denegado("No puedes modificar eso en " + col)
            f = t.una("SELECT datos,ver FROM registros WHERE id=? AND coleccion=?", (rid, col))
            if not f:
                raise NoExiste("El registro no existe")
            if "ver" in op and op["ver"] != f["ver"]:
                raise Conflicto("El registro cambió; vuelve a cargarlo")
            ant = json.loads(f["datos"])
            t.ejecutar("UPDATE registros SET datos=?,ver=ver+1 WHERE id=?", (json.dumps({**ant, **cambios}), rid))
            res.append({"id": rid, "ver": f["ver"] + 1})
            auditar(t, u, "actualizar", col, rid, {k: [ant.get(k), v] for k, v in cambios.items()})
        elif tipo == "borrar":
            if not per.puede_borrar(rol, col):
                raise Denegado("Solo el administrador puede borrar")
            rid = _entero(_resolver(op.get("id"), ids))
            if not t.una("SELECT 1 AS x FROM registros WHERE id=? AND coleccion=?", (rid, col)):
                raise NoExiste("El registro no existe")
            t.ejecutar("DELETE FROM registros WHERE id=?", (rid,))
            res.append({"id": rid, "ver": 0})
            auditar(t, u, "borrar", col, rid)
        else:
            raise Error("Operación desconocida")
        ids.append(res[-1]["id"])
    return res


def _regs(t, col):
    return [(r["id"], json.loads(r["datos"])) for r in
            t.filas("SELECT id,datos FROM registros WHERE coleccion=? ORDER BY id", (col,))]


def _guardar(t, rid, datos):
    t.ejecutar("UPDATE registros SET datos=?,ver=ver+1 WHERE id=?", (json.dumps(datos), rid))


def _cobrar(t, d, fecha):
    cats, pagos, dps = _regs(t, "cats"), _regs(t, "pagos"), dict(_regs(t, "dp"))
    cat = next((i for i, c in cats if c.get("n") == "Venta de pan"), None) \
        or next((i for i, c in cats if c.get("t") == "ingreso"), None)
    pago = next((i for i, p in pagos if re.search("efectivo", p.get("n", ""), re.I)), None) \
        or (pagos[0][0] if pagos else None)
    if cat is None or pago is None:
        raise Error("Faltan categorías o métodos de pago configurados")
    nombre = (dps.get(d.get("d")) or {}).get("n", "")
    mov = {"f": fecha, "t": "ingreso", "m": d.get("tot", 0), "c": cat, "p": pago,
           "d": "Despensa: " + nombre, "o": "despensa", "an": 0}
    _crear_registro(t, nuevo_id(t), "movs", mov)
    d["cob"] = 1


def accion_pedido(t, u, rid, accion, tz="America/Asuncion"):
    """Pasos del reparto. Hacerlos aquí permite que el repartidor no tenga acceso directo
    al stock ni a las finanzas: el servidor aplica los cambios por él."""
    if not per.puede_operar_pedidos(u["rol"]):
        raise Denegado("No puedes operar pedidos")
    f = t.una("SELECT datos FROM registros WHERE id=? AND coleccion='od'", (rid,))
    if not f:
        raise NoExiste("El pedido no existe")
    d, fecha = json.loads(f["datos"]), hoy(tz)
    if accion == "enruta":
        if d.get("e") != "pendiente":
            raise Error("El pedido no está pendiente")
        d["e"] = "en ruta"
    elif accion in ("entregar", "entregar_cobrado"):
        if d.get("e") == "entregado":
            raise Error("El pedido ya fue entregado")
        d["e"] = "entregado"
        for l in d.get("l", []):
            p = t.una("SELECT datos FROM registros WHERE id=? AND coleccion='pro'", (l.get("p"),))
            if p:
                pd = json.loads(p["datos"])
                pd["st"] = pd.get("st", 0) - l.get("q", 0)
                _guardar(t, l["p"], pd)
        if accion == "entregar_cobrado":
            _cobrar(t, d, fecha)
    elif accion == "cobrar":
        if d.get("e") != "entregado" or d.get("cob"):
            raise Error("No hay nada por cobrar")
        _cobrar(t, d, fecha)
    else:
        raise Error("Acción desconocida")
    _guardar(t, rid, d)
    auditar(t, u, accion, "od", rid, {"e": d["e"], "cob": d.get("cob", 0)})
    return d

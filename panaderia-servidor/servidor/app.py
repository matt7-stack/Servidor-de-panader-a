"""Servidor web de la panadería: login, roles y datos compartidos."""
import json
import os
import re
from datetime import timedelta
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session

from . import datos as dt
from . import permisos as per
from . import seguridad as seg
from .bd import BD

USUARIO_RE = re.compile(r"^[a-z0-9._-]{3,30}$")


def crear_app(config=None):
    cfg = {
        "SECRET_KEY": os.environ.get("SECRET_KEY"),
        "DATABASE_URL": os.environ.get("DATABASE_URL", "sqlite:///panaderia.db"),
        "ENV": os.environ.get("ENV", "desarrollo"),
        "TZ": os.environ.get("TZ_NEGOCIO", "America/Asuncion"),
        "ADMIN_USER": os.environ.get("ADMIN_USER"),
        "ADMIN_PASS": os.environ.get("ADMIN_PASS"),
    }
    cfg.update(config or {})
    prod = cfg["ENV"] == "produccion"
    if prod and not cfg["SECRET_KEY"]:
        raise RuntimeError("Falta SECRET_KEY en producción")

    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=cfg["SECRET_KEY"] or os.urandom(32).hex(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=prod,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=1_000_000,
    )
    bd = BD(cfg["DATABASE_URL"])
    lim = seg.Limitador()
    app.bd = bd

    # Primer administrador a partir de variables de entorno (solo si no hay usuarios)
    if cfg["ADMIN_USER"] and cfg["ADMIN_PASS"]:
        with bd.tx() as t:
            if not t.una("SELECT 1 AS x FROM usuarios LIMIT 1"):
                if not seg.clave_valida(cfg["ADMIN_PASS"]):
                    raise RuntimeError("ADMIN_PASS debe tener al menos 10 caracteres")
                uid = t.insertar(
                    "INSERT INTO usuarios(usuario,nombre,rol,clave,creado) VALUES(?,?,?,?,?)",
                    (cfg["ADMIN_USER"].strip().lower(), "Administrador", "admin", seg.hashear(cfg["ADMIN_PASS"]), dt.ahora()))
                dt.auditar(t, None, "crear_admin_inicial", "usuarios", uid)

    def err(msg, codigo):
        return jsonify({"error": msg}), codigo

    def actual():
        uid = session.get("uid")
        if not uid:
            return None
        with bd.tx(escritura=False) as t:
            u = t.una("SELECT id,usuario,nombre,rol,sv FROM usuarios WHERE id=? AND activo=1", (uid,))
        return u if u and u["sv"] == session.get("sv") else None

    def requiere(*roles):
        def deco(f):
            @wraps(f)
            def w(*a, **k):
                u = actual()
                if not u:
                    return err("Inicia sesión", 401)
                if roles and u["rol"] not in roles:
                    return err("No tienes permiso", 403)
                g.user = u
                return f(*a, **k)
            return w
        return deco

    def yo(u):
        return {"id": u["id"], "usuario": u["usuario"], "nombre": u["nombre"], "rol": u["rol"],
                "leer": sorted(per.LEER[u["rol"]])}

    @app.before_request
    def proteger():
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-Requested-With") != "panaderia":
            return err("Solicitud no permitida", 403)

    @app.after_request
    def cabeceras(r):
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            r.headers["Cache-Control"] = "no-store"
        else:
            r.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        return r

    @app.errorhandler(dt.Error)
    def error_negocio(e):
        return err(str(e), e.codigo)

    @app.errorhandler(413)
    def grande(_):
        return err("Solicitud demasiado grande", 413)

    @app.get("/")
    def inicio():
        return send_from_directory(os.path.join(app.root_path, "static"), "index.html")

    @app.get("/api/salud")
    def salud():
        return jsonify({"ok": True})

    # ---------- sesión ----------
    @app.post("/api/login")
    def login():
        d = request.get_json(silent=True) or {}
        usuario, clave = str(d.get("usuario", "")).strip().lower(), str(d.get("clave", ""))
        k = "%s|%s" % (request.remote_addr, usuario)
        if lim.bloqueado(k):
            return err("Demasiados intentos. Espera 15 minutos.", 429)
        with bd.tx(escritura=False) as t:
            f = t.una("SELECT * FROM usuarios WHERE usuario=? AND activo=1", (usuario,))
        ok = seg.verificar(clave, f["clave"] if f else seg.hash_falso())
        if not (f and ok):
            lim.fallo(k)
            with bd.tx() as t:
                dt.auditar(t, None, "login_fallido", detalle={"usuario": usuario[:50]})
            return err("Usuario o contraseña incorrectos", 401)
        lim.ok(k)
        session.clear()
        session.update(uid=f["id"], sv=f["sv"])
        session.permanent = True
        with bd.tx() as t:
            dt.auditar(t, f, "login")
        return jsonify(yo(f))

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/yo")
    @requiere()
    def quien():
        return jsonify(yo(g.user))

    @app.post("/api/yo/clave")
    @requiere()
    def cambiar_clave():
        d = request.get_json(silent=True) or {}
        if not seg.clave_valida(d.get("nueva")):
            return err("La contraseña nueva debe tener al menos 10 caracteres", 400)
        k = "clave|%s" % g.user["id"]
        if lim.bloqueado(k):
            return err("Demasiados intentos. Espera 15 minutos.", 429)
        with bd.tx() as t:
            f = t.una("SELECT clave,sv FROM usuarios WHERE id=?", (g.user["id"],))
            if not seg.verificar(str(d.get("actual", "")), f["clave"]):
                lim.fallo(k)
                return err("La contraseña actual no es correcta", 400)
            lim.ok(k)
            t.ejecutar("UPDATE usuarios SET clave=?,sv=sv+1 WHERE id=?", (seg.hashear(d["nueva"]), g.user["id"]))
            dt.auditar(t, g.user, "cambiar_clave", "usuarios", g.user["id"])
            session["sv"] = f["sv"] + 1  # esta sesión sigue válida; las demás se cierran
        return jsonify({"ok": True})

    # ---------- usuarios (solo administrador) ----------
    @app.get("/api/usuarios")
    @requiere("admin")
    def listar_usuarios():
        with bd.tx(escritura=False) as t:
            return jsonify(t.filas("SELECT id,usuario,nombre,rol,activo,creado FROM usuarios ORDER BY id"))

    @app.post("/api/usuarios")
    @requiere("admin")
    def crear_usuario():
        d = request.get_json(silent=True) or {}
        usuario, nombre = str(d.get("usuario", "")).strip().lower(), str(d.get("nombre", "")).strip()[:60]
        if not USUARIO_RE.match(usuario):
            return err("Usuario: 3 a 30 caracteres (letras minúsculas, números, punto, guion)", 400)
        if d.get("rol") not in per.ROLES or not nombre:
            return err("Faltan el nombre o el rol", 400)
        if not seg.clave_valida(d.get("clave")):
            return err("La contraseña debe tener al menos 10 caracteres", 400)
        with bd.tx() as t:
            if t.una("SELECT 1 AS x FROM usuarios WHERE usuario=?", (usuario,)):
                raise dt.Conflicto("Ese usuario ya existe")
            uid = t.insertar("INSERT INTO usuarios(usuario,nombre,rol,clave,creado) VALUES(?,?,?,?,?)",
                             (usuario, nombre, d["rol"], seg.hashear(d["clave"]), dt.ahora()))
            dt.auditar(t, g.user, "crear_usuario", "usuarios", uid, {"usuario": usuario, "rol": d["rol"]})
        return jsonify({"id": uid}), 201

    @app.patch("/api/usuarios/<int:uid>")
    @requiere("admin")
    def editar_usuario(uid):
        d = request.get_json(silent=True) or {}
        with bd.tx() as t:
            f = t.una("SELECT * FROM usuarios WHERE id=?", (uid,))
            if not f:
                raise dt.NoExiste("El usuario no existe")
            nuevo = {"nombre": f["nombre"], "rol": f["rol"], "activo": f["activo"], "clave": f["clave"], "sv": f["sv"]}
            if "nombre" in d:
                nuevo["nombre"] = str(d["nombre"]).strip()[:60] or f["nombre"]
            if "rol" in d:
                if d["rol"] not in per.ROLES:
                    raise dt.Error("Rol inválido")
                nuevo["rol"] = d["rol"]
            if "activo" in d:
                nuevo["activo"] = 1 if d["activo"] else 0
            if "clave" in d:
                if not seg.clave_valida(d["clave"]):
                    raise dt.Error("La contraseña debe tener al menos 10 caracteres")
                nuevo["clave"] = seg.hashear(d["clave"])
            if f["rol"] == "admin" and f["activo"] and (nuevo["rol"] != "admin" or not nuevo["activo"]):
                if t.una("SELECT COUNT(*) AS n FROM usuarios WHERE rol='admin' AND activo=1")["n"] <= 1:
                    raise dt.Error("Debe quedar al menos un administrador activo")
            if nuevo["rol"] != f["rol"] or nuevo["activo"] != f["activo"] or nuevo["clave"] != f["clave"]:
                nuevo["sv"] = f["sv"] + 1  # cierra las sesiones abiertas de ese usuario
            t.ejecutar("UPDATE usuarios SET nombre=?,rol=?,activo=?,clave=?,sv=? WHERE id=?",
                       (nuevo["nombre"], nuevo["rol"], nuevo["activo"], nuevo["clave"], nuevo["sv"], uid))
            dt.auditar(t, g.user, "editar_usuario", "usuarios", uid,
                       {k: v for k, v in d.items() if k != "clave"} | ({"clave": "cambiada"} if "clave" in d else {}))
        return jsonify({"ok": True})

    # ---------- datos ----------
    @app.get("/api/datos")
    @requiere()
    def leer_datos():
        out = {}
        with bd.tx(escritura=False) as t:
            for col in sorted(per.LEER[g.user["rol"]]):
                out[col] = [{"id": r["id"], "ver": r["ver"], **json.loads(r["datos"])} for r in
                            t.filas("SELECT id,datos,ver FROM registros WHERE coleccion=? ORDER BY id", (col,))]
        return jsonify(out)

    @app.post("/api/ids")
    @requiere()
    def ids():
        try:
            n = int((request.get_json(silent=True) or {}).get("n", 200))
        except (TypeError, ValueError):
            return err("Cantidad inválida", 400)
        with bd.tx() as t:
            return jsonify(dt.reservar(t, g.user, n))

    @app.post("/api/lote")
    @requiere()
    def lote():
        ops = (request.get_json(silent=True) or {}).get("ops")
        if not isinstance(ops, list) or not ops or len(ops) > 100:
            return err("Envía entre 1 y 100 operaciones", 400)
        with bd.tx() as t:
            res = dt.aplicar(t, g.user, ops)
        return jsonify({"resultados": res})

    @app.post("/api/pedidos/<int:rid>/<accion>")
    @requiere()
    def pedido(rid, accion):
        with bd.tx() as t:
            d = dt.accion_pedido(t, g.user, rid, accion, cfg["TZ"])
        return jsonify({"id": rid, **d})

    @app.get("/api/auditoria")
    @requiere("admin")
    def auditoria():
        try:
            n = max(1, min(500, int(request.args.get("limite", 100))))
        except ValueError:
            n = 100
        with bd.tx(escritura=False) as t:
            return jsonify(t.filas("SELECT * FROM auditoria ORDER BY id DESC LIMIT ?", (n,)))

    return app

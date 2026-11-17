import os
import tempfile
import unittest

from servidor import seguridad as seg
from servidor.app import crear_app

H = {"X-Requested-With": "panaderia"}
CLAVE = "clave-larga-123"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.app = crear_app({"DATABASE_URL": "sqlite:///" + os.path.join(self.dir.name, "t.db"),
                              "SECRET_KEY": "x", "ENV": "test", "ADMIN_USER": "yo", "ADMIN_PASS": CLAVE})
        self.admin = self.entrar("yo", CLAVE)
        for u, r in [("duena", "dueno"), ("pana", "panadero"), ("repa", "repartidor")]:
            res = self.admin.post("/api/usuarios", json={"usuario": u, "nombre": u, "rol": r, "clave": CLAVE}, headers=H)
            self.assertEqual(res.status_code, 201)
        self.dueno, self.pana, self.repa = (self.entrar(u, CLAVE) for u in ("duena", "pana", "repa"))

    def tearDown(self):
        self.dir.cleanup()

    def entrar(self, u, c):
        cl = self.app.test_client()
        r = cl.post("/api/login", json={"usuario": u, "clave": c}, headers=H)
        self.assertEqual(r.status_code, 200, r.get_json())
        return cl

    def lote(self, cl, ops):
        return cl.post("/api/lote", json={"ops": ops}, headers=H)

    def crear(self, cl, col, datos):
        r = self.lote(cl, [{"op": "crear", "col": col, "datos": datos}])
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()["resultados"][0]["id"]

    def semilla(self):
        self.cat = self.crear(self.admin, "cats", {"n": "Venta de pan", "t": "ingreso"})
        self.pago = self.crear(self.admin, "pagos", {"n": "Efectivo"})
        self.pro = self.crear(self.admin, "pro", {"n": "Pan francés", "pr": 1500, "st": 100, "rc": []})
        self.dp = self.crear(self.admin, "dp", {"n": "Almacén Don Pedro", "t": "0981", "z": "Centro", "dir": "x"})
        self.od = self.crear(self.admin, "od", {"d": self.dp, "f": "2026-11-15", "l": [{"p": self.pro, "q": 30}],
                                                "tot": 45000, "e": "pendiente", "cob": 0})


class Seguridad(unittest.TestCase):
    def test_hash_correcto_e_incorrecto(self):
        h = seg.hashear("una-clave-larga")
        self.assertTrue(seg.verificar("una-clave-larga", h))
        self.assertFalse(seg.verificar("otra-clave-larga", h))
        self.assertNotEqual(h, seg.hashear("una-clave-larga"))
        self.assertFalse(seg.verificar("x", "basura"))


class Acceso(Base):
    def test_login_incorrecto_y_bloqueo(self):
        cl = self.app.test_client()
        for _ in range(5):
            self.assertEqual(cl.post("/api/login", json={"usuario": "yo", "clave": "mala"}, headers=H).status_code, 401)
        self.assertEqual(cl.post("/api/login", json={"usuario": "yo", "clave": CLAVE}, headers=H).status_code, 429)

    def test_sin_sesion_no_hay_datos(self):
        self.assertEqual(self.app.test_client().get("/api/datos").status_code, 401)

    def test_exige_cabecera_en_escrituras(self):
        self.assertEqual(self.admin.post("/api/lote", json={"ops": []}).status_code, 403)

    def test_cambio_de_clave_cierra_sesion(self):
        uid = next(u["id"] for u in self.admin.get("/api/usuarios").get_json() if u["usuario"] == "pana")
        self.assertEqual(self.pana.get("/api/yo").status_code, 200)
        self.assertEqual(self.admin.patch("/api/usuarios/%d" % uid, json={"clave": "nueva-clave-456"}, headers=H).status_code, 200)
        self.assertEqual(self.pana.get("/api/yo").status_code, 401)

    def test_cambiar_mi_clave(self):
        mal = self.pana.post("/api/yo/clave", json={"actual": "incorrecta-123", "nueva": "nueva-clave-456"}, headers=H)
        self.assertEqual(mal.status_code, 400)
        corta = self.pana.post("/api/yo/clave", json={"actual": CLAVE, "nueva": "corta"}, headers=H)
        self.assertEqual(corta.status_code, 400)
        ok = self.pana.post("/api/yo/clave", json={"actual": CLAVE, "nueva": "nueva-clave-456"}, headers=H)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.pana.get("/api/yo").status_code, 200)  # sigue dentro
        otra = self.app.test_client()
        self.assertEqual(otra.post("/api/login", json={"usuario": "pana", "clave": CLAVE}, headers=H).status_code, 401)
        self.assertEqual(otra.post("/api/login", json={"usuario": "pana", "clave": "nueva-clave-456"}, headers=H).status_code, 200)

    def test_ultimo_admin_protegido(self):
        r = self.admin.patch("/api/usuarios/1", json={"rol": "dueno"}, headers=H)
        self.assertEqual(r.status_code, 400)

    def test_solo_admin_ve_usuarios_y_auditoria(self):
        for cl in (self.dueno, self.pana, self.repa):
            self.assertEqual(cl.get("/api/usuarios").status_code, 403)
            self.assertEqual(cl.get("/api/auditoria").status_code, 403)
        self.assertGreater(len(self.admin.get("/api/auditoria").get_json()), 0)


class Roles(Base):
    def test_lectura_por_rol(self):
        self.semilla()
        self.crear(self.admin, "movs", {"f": "2026-11-14", "t": "ingreso", "m": 5, "c": self.cat, "p": self.pago, "o": "manual", "an": 0})
        self.assertIn("movs", self.dueno.get("/api/datos").get_json())
        self.assertNotIn("movs", self.pana.get("/api/datos").get_json())
        self.assertEqual(set(self.repa.get("/api/datos").get_json()), {"od", "dp"})

    def test_dueno_registra_pero_no_modifica(self):
        self.semilla()
        mov = {"f": "2026-11-14", "t": "gasto", "m": 100, "c": self.cat, "p": self.pago, "o": "manual", "an": 0}
        mid = self.crear(self.dueno, "movs", mov)
        r = self.lote(self.dueno, [{"op": "actualizar", "col": "movs", "id": mid, "datos": {"an": 1}}])
        self.assertEqual(r.status_code, 403)
        r = self.lote(self.dueno, [{"op": "crear", "col": "movs", "datos": {**mov, "o": "despensa"}}])
        self.assertEqual(r.status_code, 403)
        r = self.lote(self.dueno, [{"op": "borrar", "col": "movs", "id": mid}])
        self.assertEqual(r.status_code, 403)

    def test_panadero_solo_toca_stock(self):
        self.semilla()
        ok = self.lote(self.pana, [{"op": "actualizar", "col": "pro", "id": self.pro, "datos": {"st": 120}}])
        self.assertEqual(ok.status_code, 200)
        mal = self.lote(self.pana, [{"op": "actualizar", "col": "pro", "id": self.pro, "datos": {"pr": 1}}])
        self.assertEqual(mal.status_code, 403)
        self.assertEqual(self.lote(self.pana, [{"op": "crear", "col": "movs", "datos": {"m": 1}}]).status_code, 403)
        self.assertEqual(self.lote(self.pana, [{"op": "crear", "col": "sm", "datos": {"t": "consumo", "q": -2}}]).status_code, 200)

    def test_repartidor_no_escribe_directo(self):
        self.semilla()
        r = self.lote(self.repa, [{"op": "actualizar", "col": "od", "id": self.od, "datos": {"e": "entregado"}}])
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.lote(self.repa, [{"op": "crear", "col": "movs", "datos": {"m": 1}}]).status_code, 403)


class Datos(Base):
    def test_lote_atomico_y_referencias(self):
        r = self.lote(self.admin, [
            {"op": "crear", "col": "comps", "datos": {"tot": 10}},
            {"op": "crear", "col": "movs", "datos": {"o": "compra", "cp": "$0", "m": 10}},
        ])
        self.assertEqual(r.status_code, 200)
        datos = self.admin.get("/api/datos").get_json()
        self.assertEqual(datos["movs"][0]["cp"], datos["comps"][0]["id"])
        r = self.lote(self.admin, [
            {"op": "crear", "col": "cats", "datos": {"n": "A", "t": "gasto"}},
            {"op": "crear", "col": "no_existe", "datos": {}},
        ])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.admin.get("/api/datos").get_json()["cats"], [])

    def test_conflicto_de_version(self):
        cid = self.crear(self.admin, "cats", {"n": "A", "t": "gasto"})
        a = self.lote(self.admin, [{"op": "actualizar", "col": "cats", "id": cid, "ver": 1, "datos": {"n": "B"}}])
        self.assertEqual(a.status_code, 200)
        b = self.lote(self.admin, [{"op": "actualizar", "col": "cats", "id": cid, "ver": 1, "datos": {"n": "C"}}])
        self.assertEqual(b.status_code, 409)

    def test_admin_borra(self):
        cid = self.crear(self.admin, "cats", {"n": "A", "t": "gasto"})
        self.assertEqual(self.lote(self.admin, [{"op": "borrar", "col": "cats", "id": cid}]).status_code, 200)
        self.assertEqual(self.admin.get("/api/datos").get_json()["cats"], [])


class Identificadores(Base):
    def test_ids_reservados(self):
        r = self.admin.post("/api/ids", json={"n": 10}, headers=H).get_json()
        d = r["desde"]
        ok = self.lote(self.admin, [{"op": "crear", "col": "cats", "id": d, "datos": {"n": "A", "t": "gasto"}}])
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.admin.get("/api/datos").get_json()["cats"][0]["id"], d)
        dup = self.lote(self.admin, [{"op": "crear", "col": "cats", "id": d, "datos": {"n": "B", "t": "gasto"}}])
        self.assertEqual(dup.status_code, 409)
        fuera = self.lote(self.admin, [{"op": "crear", "col": "cats", "id": d + 50, "datos": {"n": "C", "t": "gasto"}}])
        self.assertEqual(fuera.status_code, 403)
        ajeno = self.lote(self.pana, [{"op": "crear", "col": "sm", "id": d + 1, "datos": {"t": "consumo", "q": -1}}])
        self.assertEqual(ajeno.status_code, 403)

    def test_bloques_distintos_y_sin_choque_con_ids_del_servidor(self):
        a = self.admin.post("/api/ids", json={"n": 5}, headers=H).get_json()
        b = self.pana.post("/api/ids", json={"n": 5}, headers=H).get_json()
        self.assertGreater(b["desde"], a["desde"] + 4)
        self.semilla()
        self.repa.post("/api/pedidos/%d/entregar_cobrado" % self.od, headers=H)
        usados = [m["id"] for m in self.admin.get("/api/datos").get_json()["movs"]]
        self.assertTrue(all(not (a["desde"] <= i < a["desde"] + 5 or b["desde"] <= i < b["desde"] + 5) for i in usados))


class Reparto(Base):
    def test_entregar_y_cobrar(self):
        self.semilla()
        r = self.repa.post("/api/pedidos/%d/entregar_cobrado" % self.od, headers=H)
        self.assertEqual(r.status_code, 200, r.get_json())
        d = self.admin.get("/api/datos").get_json()
        self.assertEqual(d["od"][0]["e"], "entregado")
        self.assertEqual(d["od"][0]["cob"], 1)
        self.assertEqual(d["pro"][0]["st"], 70)
        self.assertEqual(d["movs"][0]["o"], "despensa")
        self.assertEqual(d["movs"][0]["m"], 45000)
        self.assertEqual(self.repa.post("/api/pedidos/%d/entregar" % self.od, headers=H).status_code, 400)
        self.assertEqual(len(self.admin.get("/api/datos").get_json()["movs"]), 1)

    def test_entregar_sin_cobrar_y_cobrar_despues(self):
        self.semilla()
        self.assertEqual(self.repa.post("/api/pedidos/%d/entregar" % self.od, headers=H).status_code, 200)
        self.assertNotIn("movs", self.repa.get("/api/datos").get_json())
        self.assertEqual(self.repa.post("/api/pedidos/%d/cobrar" % self.od, headers=H).status_code, 200)
        self.assertEqual(self.repa.post("/api/pedidos/%d/cobrar" % self.od, headers=H).status_code, 400)

    def test_otros_roles_no_operan_pedidos(self):
        self.semilla()
        for cl in (self.pana, self.dueno):
            self.assertEqual(cl.post("/api/pedidos/%d/entregar" % self.od, headers=H).status_code, 403)


if __name__ == "__main__":
    unittest.main()

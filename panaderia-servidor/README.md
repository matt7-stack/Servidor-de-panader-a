# Servidor de Panadería Gestión

Servidor web con **inicio de sesión, roles y datos compartidos**. Los permisos los aplica el servidor, no la pantalla.

## Roles

| | Administrador | Dueño | Panadero | Repartidor |
|---|---|---|---|---|
| Crear, editar, anular y borrar registros | Sí | No | No | No |
| Usuarios, configuración y auditoría | Sí | No | No | No |
| Ver finanzas, empleados y reportes | Sí | Sí | No | No |
| Registrar ingresos y gastos manuales | Sí | Sí | No | No |
| Ajustar stock de insumos y productos, registrar consumos y mermas | Sí | No | Sí | No |
| Ver pedidos de despensas | Sí | Sí | Sí | Sí |
| Marcar en ruta, entregar y cobrar | Sí | No | No | Sí |

Cada cambio queda en el registro de auditoría (quién, qué, cuándo y el valor anterior).

## Probar en tu computadora

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install flask
python crear_admin.py          # crea el primer administrador
flask --app servidor.app:crear_app run
```

Abre http://127.0.0.1:5000 e inicia sesión. Para correr las pruebas:

```bash
python3 -m unittest discover -s tests -t .
```

## Publicarlo en internet (Neon + Render)

1. **Base de datos:** un proyecto de Neon con una base PostgreSQL. Copia su cadena de conexión (`DATABASE_URL`) desde el botón *Connect* de Neon.
2. **Código:** sube el **contenido** de esta carpeta (no la carpeta misma, para que `requirements.txt` quede en la raíz) a un repositorio de GitHub.
3. **Servicio web en Render:** tipo *Python*, con
   - build: `pip install -r requirements.txt`
   - arranque: `gunicorn wsgi:app`
   - región: Virginia u Ohio (las más cercanas a Paraguay).
4. **Variables de entorno:**
   - `ENV=produccion`
   - `SECRET_KEY`: un texto largo y aleatorio
   - `DATABASE_URL`: la de Neon
   - `ADMIN_USER` y `ADMIN_PASS` (mínimo 10 caracteres): crean el primer administrador al arrancar. Quita `ADMIN_PASS` cuando ya hayas entrado.
5. Entra con el administrador. En **Más → Usuarios** creas las cuentas del dueño, el panadero y el repartidor; cada uno puede cambiar su contraseña con el botón *Contraseña*.

## API

| Ruta | Quién | Qué hace |
|---|---|---|
| `POST /api/login`, `/api/logout`, `GET /api/yo` | Todos | Sesión |
| `POST /api/ids` | Todos | Reserva identificadores para los registros nuevos de ese dispositivo |
| `GET /api/datos` | Todos | Devuelve solo las colecciones que el rol puede leer |
| `POST /api/lote` | Según rol | Crear, actualizar o borrar varios registros a la vez; todo o nada. Se puede usar `"$0"` para referirse al id de la operación 0 |
| `POST /api/pedidos/<id>/<accion>` | Admin, repartidor | `enruta`, `entregar`, `entregar_cobrado`, `cobrar` |
| `GET/POST/PATCH /api/usuarios` | Admin | Gestión de usuarios (en la interfaz: Más → Usuarios) |
| `POST /api/yo/clave` | Todos | Cambiar la contraseña propia |
| `GET /api/auditoria` | Admin | Historial de cambios |

Las escrituras exigen la cabecera `X-Requested-With: panaderia`.

## La interfaz

`servidor/static/index.html` es la aplicación completa (la misma del prototipo) conectada al servidor:

- Pantalla de acceso con usuario y contraseña. Cada rol ve solo sus pantallas: el administrador y el dueño ven todo el negocio; el panadero, insumos, productos y lo que hay que preparar; el repartidor, solo sus entregas.
- **Primer uso:** al entrar el administrador con el sistema vacío, elige entre empezar vacío (con categorías y métodos de pago básicos) o cargar datos de ejemplo.
- Los botones que un rol no puede usar se ocultan, pero **eso es solo comodidad**: quien decide es el servidor, que rechaza cualquier cambio no permitido y recarga los datos.
- Cada cambio se guarda en el servidor al instante. Si dos personas editan lo mismo, el segundo recibe un aviso y se recargan los datos. Cada 20 segundos se actualizan los datos de los demás.
- El repartidor entrega y cobra con botones que llaman al servidor; es el servidor quien descuenta el stock y registra el ingreso.

## Pruebas

- `python3 -m unittest discover -s tests -t .`: 20 pruebas del servidor (SQLite).
- `tests/e2e.js` (necesita Node 18 o más y el servidor corriendo en el puerto 5055 con `ADMIN_USER=yo` y `ADMIN_PASS=clave-larga-123`): carga la interfaz real con cada rol y comprueba que lo que guarda uno lo ve otro, que el servidor rechaza lo que no corresponde y que todas las pantallas se dibujan. Se ejecutó completa sin errores.

## Estado y límites

- **PostgreSQL no se ha probado.** Todas las pruebas usaron SQLite. Pruébalo en una base de ensayo antes de usarlo con datos reales.
- Ocultar botones no es seguridad; la seguridad está en el servidor. Aun así, el panadero puede ajustar el stock a cualquier número (queda en la auditoría con el valor anterior).
- No hay actualización en tiempo real: los cambios de otras personas aparecen en hasta 20 segundos.
- El límite de intentos de acceso vive en memoria: se reinicia con el servidor y no se comparte entre procesos.
- No hay recuperación de contraseña por correo: si alguien la olvida, el administrador le pone una nueva en Más → Usuarios.
- Se quitó la función «restaurar copia» de la interfaz, porque no encaja con identificadores asignados por el servidor. Haz copias de seguridad de la base de datos en el servidor.
- Los datos se guardan como registros JSON por colección. Si el sistema crece, se puede pasar a tablas normalizadas.

const vm = require('vm'), fs = require('fs'), assert = require('assert');
const BASE = 'http://127.0.0.1:5055';
const html = fs.readFileSync('/home/claude/panaderia-servidor/servidor/static/index.html', 'utf8');
const script = html.slice(html.indexOf('<script>') + 8, html.indexOf('</script>'));

function mkfetch() {
  let cookie = '';
  return async (u, o = {}) => {
    const h = { ...(o.headers || {}) }; if (cookie) h.Cookie = cookie;
    const r = await fetch(BASE + u, { ...o, headers: h });
    for (const c of (r.headers.getSetCookie ? r.headers.getSetCookie() : [])) cookie = c.split(';')[0];
    return r;
  };
}
function mkel() { return { style: {}, dataset: {}, value: '', textContent: '', innerHTML: '', onclick: null, disabled: false,
  addEventListener() {}, select() {}, insertAdjacentHTML() {}, files: [], tagName: 'DIV' }; }

async function cliente(usuario, clave) {
  const els = {}, handlers = {};
  const sandbox = {
    fetch: mkfetch(), console, setTimeout, setInterval: () => {}, location: { reload() {} },
    document: { body: { className: '' }, activeElement: null,
      querySelector: s => (els[s] ||= mkel()), querySelectorAll: () => [],
      addEventListener: (t, f) => { handlers[t] = f; } },
    FormData: class { constructor(f) { this.f = f.fields; } *[Symbol.iterator]() { yield* Object.entries(this.f); }
      getAll(k) { return [].concat(this.f[k] ?? []); } },
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(script, ctx);
  await new Promise(r => setTimeout(r, 300));
  const run = code => vm.runInContext(code, ctx);
  els['#lgu'] ||= mkel(); els['#lgc'] ||= mkel(); els['#lgu'].value = usuario; els['#lgc'].value = clave;
  await run('entrar()');
  const submit = async (f, fields, t) => { await handlers.submit({ preventDefault() {}, target: { dataset: { f, ...(t ? { t } : {}) }, fields } }); await run('QS'); };
  const click = async a => { await handlers.click({ target: { closest: () => ({ dataset: { a } }) } }); await run('QS'); };
  return { run, els, submit, click };
}
const lim = o => JSON.stringify(o);
const colecciones = ['movs', 'cats', 'pagos', 'provs', 'ins', 'comps', 'sm', 'emp', 'pe', 'pro', 'pm', 'pd', 'dp', 'od', 'rc', 'cj'];
const ord = v => Array.isArray(v) ? v.map(ord) : (v && typeof v === 'object') ? Object.fromEntries(Object.keys(v).sort().map(k => [k, ord(v[k])])) : v;
const sinVer = a => lim(ord(a.map(({ ver, ...r }) => r)));

(async () => {
  const A = await cliente('yo', 'clave-larga-123');
  assert.equal(await A.run('ME.rol'), 'admin'); assert.equal(await A.run('S.cats.length'), 0);
  console.log('OK login admin; sistema vacío');
  await A.run('R()'); assert(A.els['#v'].innerHTML.includes('Primer uso'));
  await A.click('ini1'); await A.run('QS');
  const n = await A.run('S.movs.length'); assert(n > 50, 'movs ' + n);
  const srv = await A.run("api('/api/datos').then(x=>x[1])");
  for (const c of colecciones) assert.equal(srv[c].length, await A.run(`S.${c}.length`), c);
  console.log('OK datos de ejemplo guardados en el servidor:', n, 'movimientos');

  await A.run("S.movs[0].m=12345; S.movs.push({id:id(),f:T,t:'gasto',m:777,c:S.cats.find(c=>c.t=='gasto').id,p:S.pagos[0].id,d:'prueba',o:'manual',an:0}); S.rc=[]; S.nom='Panadería Prueba'; S.mv='5000000'; save()");
  await A.run('QS');
  const B = await cliente('yo', 'clave-larga-123');
  for (const c of colecciones) assert(sinVer(await B.run(`S.${c}`)) === sinVer(await A.run(`S.${c}`)), 'ida y vuelta ' + c);
  assert.equal(await B.run('S.nom'), 'Panadería Prueba'); assert.equal(await B.run('S.mv'), '5000000');
  assert.equal(await B.run('S.movs[0].m'), 12345); assert.equal(await B.run('S.rc.length'), 0);
  console.log('OK edición, alta, baja y ajustes llegan igual a otro dispositivo');

  await A.run("S.cats[0].n='A'; save()"); await A.run('QS');
  await B.run("S.cats[0].n='B'; save()"); await B.run('QS');
  assert.equal(await B.run('S.cats[0].n'), 'A'); assert(B.els['#mb'].innerHTML.includes('cambió'));
  console.log('OK conflicto de versión: se recarga y avisa');

  for (const [u, r] of [['duena', 'dueno'], ['pana', 'panadero'], ['repa', 'repartidor']])
    assert.equal((await A.run(`api('/api/usuarios',{method:'POST',body:JSON.stringify({usuario:'${u}',nombre:'${u}',rol:'${r}',clave:'clave-larga-123'})})`))[0], 201);

  await A.click('mas:usr'); assert.equal(await A.run('US.length'), 4);
  await A.run("tab='mas';mas='usr';R()"); assert((await A.run('V.usr()')).includes('Panadero'));
  await A.submit('usr', { id: '', usuario: 'nuevo1', nombre: 'Nuevo Uno', rol: 'panadero', clave: 'otra-clave-123' });
  assert.equal(await A.run('US.length'), 5);
  const nid = await A.run("US.find(u=>u.usuario=='nuevo1').id");
  await A.submit('usr', { id: String(nid), nombre: 'Nuevo Dos', rol: 'dueno', clave: '', activo: '0' });
  assert.equal(await A.run(`US.find(u=>u.id==${nid}).activo`), 0); assert.equal(await A.run(`US.find(u=>u.id==${nid}).rol`), 'dueno');
  await A.submit('usr', { id: '', usuario: 'nuevo1', nombre: 'Repetido', rol: 'panadero', clave: 'otra-clave-123' });
  assert(A.els['#mb'].innerHTML.includes('ya existe'));
  console.log('OK pantalla de usuarios: crear, editar, desactivar y rechazar duplicados');
  // vistas sin errores para cada rol
  const rec = async (c, tabs) => { for (const t of tabs) { await c.run(`tab='${t}';R()`); }
    if (tabs.includes('mas')) for (const m of ['emp', 'prov', 'rep', 'caja', 'rec', 'pd', 'dp', 'rp', 'cfg']) await c.run(`tab='mas';mas='${m}';R()`);
    if (tabs.includes('mp')) for (const m of ['ins', 'comp', 'sm']) await c.run(`tab='mp';sub='${m}';R()`); };
  await rec(A, ['ini', 'ingreso', 'gasto', 'mp', 'pro', 'mas', 'caja', 'pd', 'dp', 'rp']);
  console.log('OK todas las pantallas del administrador se dibujan');

  const P = await cliente('pana', 'clave-larga-123');
  assert.equal(await P.run('ME.rol'), 'panadero'); assert.equal(await P.run('S.movs.length'), 0); assert(await P.run('S.pro.length') > 0);
  await rec(P, ['mp', 'pro', 'rp']);
  const antes = await A.run("api('/api/datos').then(x=>x[1])");
  const pro = antes.pro.find(p => p.rc.length), st0 = pro.st, ins0 = antes.ins.find(i => i.id == pro.rc[0].i).st;
  await P.submit('prod', { p: String(pro.id), f: '2026-11-15', q: '10' });
  const desp = await A.run("api('/api/datos').then(x=>x[1])");
  assert.equal(desp.pro.find(p => p.id == pro.id).st, st0 + 10);
  assert(desp.ins.find(i => i.id == pro.rc[0].i).st < ins0);
  assert(desp.sm.length > antes.sm.length);
  console.log('OK el panadero registra producción: sube el stock y baja la materia prima');
  const pr0 = await P.run('S.pro[0].pr');
  await P.run('S.pro[0].pr=1; save()'); await P.run('QS');
  assert.equal(await P.run('S.pro[0].pr'), pr0); assert(P.els['#mb'].innerHTML.includes('No puedes'));
  console.log('OK el panadero no puede cambiar precios: el servidor lo rechaza y recarga');

  await P.submit('miclave', { actual: 'clave-larga-123', nueva: 'otra-clave-999' });
  assert(P.els['#mb'].innerHTML.includes('cambiada'));
  await P.submit('miclave', { actual: 'mala', nueva: 'otra-clave-888' });
  assert(P.els['#mb'].innerHTML.includes('no es correcta'));
  console.log('OK cada usuario cambia su propia contraseña');
  const D = await cliente('duena', 'clave-larga-123');
  assert(await D.run('S.movs.length') > 50); await rec(D, ['ini', 'ingreso', 'gasto', 'mp', 'pro', 'mas']);
  const nm0 = await D.run('S.movs.length');
  await D.submit('mov', { f: '2026-11-15', m: '5000', c: String(await D.run("S.cats.find(c=>c.t=='ingreso').id")), p: String(await D.run('S.pagos[0].id')), d: 'venta mostrador' }, 'ingreso');
  assert.equal(await D.run('S.movs.length'), nm0 + 1);
  assert.equal((await A.run("api('/api/datos').then(x=>x[1].movs.length)")), nm0 + 1);
  const m1 = await D.run('S.movs[0].m'); await D.run('S.movs[0].m=1; save()'); await D.run('QS');
  assert.equal(await D.run('S.movs[0].m'), m1);
  console.log('OK el dueño registra ingresos pero no puede modificar');

  const R_ = await cliente('repa', 'clave-larga-123');
  assert.equal(await R_.run('S.movs.length'), 0); assert.deepEqual(await R_.run('Object.keys(S).filter(k=>Array.isArray(S[k])&&S[k].length).sort()'), ['dp', 'od']);
  await rec(R_, ['rp']); assert((await R_.run('V.rp()')).includes('Pan franc'));
  const od = await R_.run("S.od.find(o=>o.e=='pendiente')"); const movsAntes = (await A.run("api('/api/datos').then(x=>x[1].movs.length)"));
  await R_.run(`accion(${od.id},'entregar_cobrado')`);
  assert.equal(await R_.run(`S.od.find(o=>o.id==${od.id}).e`), 'entregado');
  const fin = await A.run("api('/api/datos').then(x=>x[1])");
  assert.equal(fin.movs.length, movsAntes + 1); assert.equal(fin.movs[fin.movs.length - 1].o, 'despensa');
  console.log('OK el repartidor entrega y cobra; el servidor descuenta stock y registra el ingreso');

  const R2 = await cliente('yo', 'clave-larga-123');
  await R2.run('S.od=[]; S.pro=S.pro.slice(1); save()'); await R2.run('QS');
  assert.equal((await A.run("api('/api/datos').then(x=>x[1].od.length)")), 0);
  console.log('OK el administrador puede borrar');
  console.log('TODO OK');
})().catch(e => { console.error('FALLO', e); process.exit(1); });

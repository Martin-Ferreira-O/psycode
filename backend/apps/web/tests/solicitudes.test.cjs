const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

function contexto() {
    const tokens = new Map([['access_token', 'prueba'], ['refresh_token', 'prueba']]);
    const redirecciones = [];
    const context = vm.createContext({
        Headers, fetch,
        document: { cookie: 'csrftoken=csrf-sintetico' },
        localStorage: { getItem: k => tokens.get(k), removeItem: k => tokens.delete(k) },
        sessionStorage: { clear() {} },
        window: { addEventListener() {}, location: { pathname: '/evaluaciones', replace: p => redirecciones.push(p) } },
    });
    for (const archivo of ['solicitudes.js', 'estados.js', 'api.js']) {
        vm.runInContext(readFileSync(join(__dirname, '../static/web/js', archivo), 'utf8'), context);
    }
    return { context, tokens, redirecciones };
}

for (const estado of [400, 401, 403, 404, 409, 503]) {
    test(`HTTP ${estado} conserva su clasificación aunque el cuerpo sea HTML`, async () => {
        const { context } = contexto();
        context.response = new Response('<html>traza interna</html>', { status: estado });
        await vm.runInContext(`leerRespuesta(response).catch(error => {
            resultado = describirError(error);
            estadoRecibido = error.estado;
        })`, context);
        assert.equal(context.estadoRecibido, estado);
        assert.ok(context.resultado.mensaje.length > 0);
        assert.ok(!context.resultado.mensaje.includes('traza'));
        assert.equal(context.resultado.recuperable, estado === 503);
    });
}

test('una lista vacía es éxito y un sobre inválido es error', async () => {
    const { context } = contexto();
    context.response = Response.json({ success: true, data: { items: [] } });
    assert.equal((await vm.runInContext('leerRespuesta(response)', context)).items.length, 0);
    for (const cuerpo of [{ success: true }, { success: false, error: { message: 'secreto' } }]) {
        context.response = Response.json(cuerpo);
        await assert.rejects(vm.runInContext('leerRespuesta(response)', context), /No se pudo/);
    }
    context.response = new Response('no JSON');
    await assert.rejects(vm.runInContext('leerRespuesta(response)', context), /No se pudo/);
});

test('las peticiones usan cookies y CSRF sin enviar tokens desde localStorage', async () => {
    const { context, tokens } = contexto();
    const requests = [];
    context.fetch = async (url, options) => {
        requests.push({ url, options });
        return Response.json({ success: true, data: {} });
    };
    await vm.runInContext('apiPost("/api/v1/alerts/test/evaluacion", {evaluacion: "correcta"})', context);
    assert.equal(tokens.size, 0);
    assert.equal(requests[0].options.credentials, 'same-origin');
    assert.equal(requests[0].options.headers.get('Authorization'), null);
    assert.equal(requests[0].options.headers.get('X-CSRFToken'), 'csrf-sintetico');
    assert.equal(requests[0].options.headers.get('X-Psycode-Browser'), '1');
});

test('401 renueva cookies una sola vez para solicitudes simultáneas', async () => {
    const { context } = contexto();
    let renewals = 0;
    let authenticated = false;
    context.fetch = async (url, options) => {
        if (url.endsWith('/refresh')) {
            renewals++;
            assert.equal(options.body, '{}');
            authenticated = true;
            return Response.json({ success: true, data: { authenticated: true } });
        }
        return authenticated ? Response.json({ success: true, data: {} }) : new Response(null, { status: 401 });
    };
    await vm.runInContext('Promise.all([apiGet("/api/v1/alerts"), apiGet("/api/v1/auth/me")])', context);
    assert.equal(renewals, 1);
});

test('logout fallido avisa y no presenta un cierre de sesión exitoso', async () => {
    const { context, redirecciones } = contexto();
    let warning = '';
    context.window.alert = message => { warning = message; };
    context.fetch = async () => new Response(null, { status: 503 });
    await vm.runInContext('cerrarSesion()', context);
    assert.deepEqual(redirecciones, []);
    assert.match(warning, /No se pudo cerrar la sesión/);
});

test('204 no intenta leer JSON', async () => {
    const { context } = contexto();
    context.response = new Response(null, { status: 204 });
    assert.equal(await vm.runInContext('leerRespuesta(response)', context), null);
});

test('fallo de red recuperable y cancelación sin mensaje', async () => {
    const { context } = contexto();
    context.fetch = async () => { throw new TypeError('detalle técnico'); };
    await vm.runInContext('solicitarJson("/").catch(e => resultado = describirError(e))', context);
    assert.equal(context.resultado.recuperable, true);
    assert.ok(!context.resultado.mensaje.includes('técnico'));
    context.fetch = async () => { const e = new Error(); e.name = 'AbortError'; throw e; };
    await vm.runInContext('solicitarJson("/").catch(e => resultado = describirError(e))', context);
    assert.equal(context.resultado.omitido, true);
});

test('401 protegido limpia sesión y delega redirección sin ofrecer reintento', async () => {
    const { context, tokens, redirecciones } = contexto();
    context.fetch = async () => new Response(null, { status: 401 });
    await vm.runInContext('apiGetDatos("/api/v1/alerts").catch(e => resultado = describirError(e))', context);
    assert.equal(tokens.size, 0);
    assert.deepEqual(redirecciones, ['/']);
    assert.equal(context.resultado.omitido, true);
    assert.equal(context.resultado.recuperable, false);
});

test('mensajes locales específicos y 401 público no redirigen', async () => {
    const { context, redirecciones } = contexto();
    context.fetch = async () => new Response(null, { status: 401 });
    await vm.runInContext(`solicitarJson('/api/v1/auth/login').catch(e => {
        resultado = describirError(e, {401: 'Usuario o contraseña incorrectos.'});
    })`, context);
    assert.deepEqual(redirecciones, []);
    assert.equal(context.resultado.mensaje, 'Usuario o contraseña incorrectos.');
    assert.equal(context.resultado.omitido, false);
});

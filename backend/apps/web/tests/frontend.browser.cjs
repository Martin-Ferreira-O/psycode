// Prueba de integración opcional: requiere Playwright y el servidor Django local.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
    });
    const page = await browser.newPage();
    const base = process.env.FRONTEND_TEST_URL || 'http://127.0.0.1:8765';
    const errores = [];
    page.on('pageerror', e => errores.push(e.message));
    let estado = 503;
    let peticiones = 0;
    let liberar;
    let cuerpo = { success: true, data: { items: [] } };
    try {
        await page.route('**/api/v1/auth/me', route => route.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify({ success: true, data: { usuario: 'supervisor-sintetico', rol: 'supervisor' } }),
        }));
        await page.route('**/api/v1/auth/refresh', route => route.fulfill({ status: 401 }));
        await page.route('**/api/v1/auth/login', async route => {
            peticiones++;
            if (liberar === null) await new Promise(resolve => { liberar = resolve; });
            await route.fulfill({ status: estado, contentType: 'text/html', body: 'TRAZA_PRIVADA' });
        });
        await page.goto(base);
        await page.locator('#username').fill('profesional');
        await page.locator('#password').fill('clave-de-prueba');
        liberar = null;
        await page.locator('#submit-btn').click();
        await page.locator('#alert-box[data-estado="carga"]').waitFor();
        assert.equal(await page.locator('#submit-btn').isDisabled(), true);
        await page.locator('#login-form').evaluate(form => form.requestSubmit());
        assert.equal(peticiones, 1, 'evita envíos duplicados durante la carga');
        liberar();
        await page.locator('#alert-box[data-estado="error"]').waitFor();
        assert.match(await page.locator('#alert-box').innerText(), /temporalmente/);
        assert.equal(await page.locator('#username').inputValue(), 'profesional');
        assert.equal(await page.locator('#password').inputValue(), 'clave-de-prueba');
        assert.equal(await page.locator('#submit-btn .btn-text').count(), 1);
        estado = 401;
        await page.getByRole('button', { name: 'Reintentar', exact: true }).click();
        await page.getByText('Usuario o contraseña incorrectos.', { exact: false }).waitFor();
        assert.equal(await page.locator('.boton-reintentar').count(), 0);
        assert.equal(new URL(page.url()).pathname, '/');
        assert.equal(await page.locator('body').innerText().then(t => t.includes('TRAZA_PRIVADA')), false);

        estado = 503;
        liberar = null;
        await page.route('**/api/v1/alerts?revisadas=true', async route => {
            if (liberar === null) await new Promise(resolve => { liberar = resolve; });
            await route.fulfill({ status: estado, contentType: 'application/json', body: JSON.stringify(cuerpo) });
        });
        await page.goto(`${base}/evaluaciones`);
        const panel = page.locator('#estadoVacioEvaluaciones');
        await page.locator('[data-estado="carga"]').waitFor();
        assert.equal(await page.locator('#tablaEvaluacionesContenedor').isVisible(), false);
        liberar();
        await page.locator('[data-estado="error"]').waitFor();
        assert.equal((await panel.innerText()).includes('Todavía no'), false);
        estado = 200;
        await page.getByRole('button', { name: 'Reintentar', exact: true }).click();
        await page.locator('[data-estado="vacio"]').waitFor();
        assert.match(await panel.innerText(), /Todavía no existen/);
        cuerpo = { success: true, data: {} };
        await page.evaluate(() => cargarEvaluaciones());
        assert.equal(await panel.getAttribute('data-estado'), 'error');
        assert.equal((await panel.innerText()).includes('Todavía no'), false);
        for (const codigo of [400, 404, 409]) {
            estado = codigo;
            await page.evaluate(() => cargarEvaluaciones());
            assert.equal(await panel.getAttribute('data-estado'), 'error');
            assert.equal(await page.locator('.boton-reintentar').count(), 0);
        }
        estado = 200;
        cuerpo = { success: true, data: { items: [{
            alerta_id: 'alerta-sintetica', box: 'box-1', tipo_riesgo: 'riesgo_suicida',
            nivel_severidad: 1, fecha_hora: '2026-09-12T15:00:00Z',
            estado_evaluacion: 'correcta', evaluacion: { evaluacion: 'correcta' },
        }] } };
        await page.evaluate(() => cargarEvaluaciones());
        assert.equal(await page.locator('#tablaEvaluacionesContenedor').isVisible(), true);
        assert.equal(await page.locator('#tablaEvaluaciones tr').count(), 1);
        estado = 503;
        await page.evaluate(() => cargarEvaluaciones());
        assert.equal(await page.locator('#tablaEvaluaciones tr').count(), 1, 'conserva datos ante fallo');
        assert.equal(await page.locator('#tablaEvaluacionesContenedor').isVisible(), false, 'no presenta datos anteriores como actuales');
        estado = 401;
        await page.evaluate(() => cargarEvaluaciones());
        await page.waitForURL(`${base}/`);
        assert.equal(await page.evaluate(() => localStorage.getItem('access_token')), null);

        const alerta = { ...cuerpo.data.items[0], estado_evaluacion: 'pendiente', evaluacion: null };
        let evaluacion = null;
        await page.route('**/api/v1/alerts**', async route => {
            const url = new URL(route.request().url());
            let data;
            if (url.pathname.endsWith('/evaluacion')) {
                assert.equal(route.request().method(), 'POST');
                assert.equal(route.request().postDataJSON().evaluacion, 'correcta');
                evaluacion = { alerta_id: alerta.alerta_id, evaluacion: 'correcta', estado_evaluacion: 'correcta',
                    usuario: 'supervisor-sintetico', fecha_hora: '2026-10-27T15:00:00Z' };
                data = evaluacion;
            } else if (url.pathname.endsWith('/' + alerta.alerta_id)) {
                data = { ...alerta, ...(evaluacion ? { evaluacion, estado_evaluacion: 'correcta' } : {}) };
            } else {
                const items = url.searchParams.has('q') ? [] : [alerta];
                data = { items, total: items.length, limit: Number(url.searchParams.get('limit') || 10), offset: 0 };
            }
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) });
        });
        await page.goto(`${base}/dashboard`);
        await page.locator('[data-alerta]').first().waitFor();
        await page.locator('#buscar').fill('sin coincidencias');
        await page.locator('#estadoVacio[data-estado="vacio"]').waitFor();
        await page.locator('#botonActualizar').click();
        await page.locator('#estadoVacio[data-estado="vacio"]').waitFor();
        assert.equal(await page.locator('#buscar').inputValue(), 'sin coincidencias');
        assert.match(await page.locator('#estadoVacio').innerText(), /filtros/);
        await page.locator('#limpiarFiltros').click();
        await page.locator('[data-alerta]').first().click();
        await page.locator('#guardarEvaluacion').click();
        assert.equal(await page.locator('#mensajeEvaluacion').getAttribute('role'), 'alert');
        await page.locator('input[name="evaluacion"][value="correcta"]').check();
        await page.evaluate(() => mostrarError(document.querySelector('#mensajeEvaluacion'), new ErrorSolicitud(503)));
        assert.equal(await page.locator('input[name="evaluacion"][value="correcta"]').isChecked(), true);
        await page.locator('#guardarEvaluacion').click();
        await page.locator('#evaluacionRegistrada').waitFor();
        assert.equal(await page.locator('#evaluacionRegistrada').isVisible(), true);
        assert.deepEqual(errores, [], 'sin errores JavaScript en las pantallas');
        console.log('Integración verificada: login, carga, reintento, estados HTTP, sesión, filtros y selección.');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });

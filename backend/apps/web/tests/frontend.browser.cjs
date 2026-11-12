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
    let cuerpo = { success: true, data: { items: [], total: 0 } };
    let registros;
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
        let confirmarConsulta;
        const primeraConsulta = new Promise(resolve => { confirmarConsulta = resolve; });
        liberar = null;
        await page.route(url => url.pathname === '/api/v1/alerts' && url.searchParams.get('registro_evaluaciones') === 'true', async route => {
            if (liberar === null) {
                await new Promise(resolve => {
                    liberar = resolve;
                    confirmarConsulta();
                });
            }
            let respuesta = cuerpo;
            if (registros) {
                const parametros = new URL(route.request().url()).searchParams;
                const limit = Number(parametros.get('limit'));
                const offset = Number(parametros.get('offset'));
                assert.equal(limit, 10);
                respuesta = { success: true, data: {
                    items: registros.slice(offset, offset + limit), total: registros.length, limit, offset,
                } };
            }
            await route.fulfill({ status: estado, contentType: 'application/json', body: JSON.stringify(respuesta) });
        });
        await page.goto(`${base}/evaluaciones`);
        const panel = page.locator('#estadoVacioEvaluaciones');
        await page.locator('#tablaEvaluacionesContenedor .ui-skeleton').first().waitFor();
        assert.equal(await page.getByRole('heading', { name: 'Registro de evaluaciones' }).isVisible(), true);
        assert.equal(await page.getByRole('columnheader', { name: 'Fecha de evaluación' }).isVisible(), true);
        assert.equal(await page.locator('.panel-evaluaciones').getAttribute('aria-busy'), 'true');
        await primeraConsulta;
        liberar();
        await page.locator('[data-estado="error"]').waitFor();
        assert.equal((await panel.innerText()).includes('Todavía no'), false);
        estado = 200;
        await page.getByRole('button', { name: 'Reintentar', exact: true }).click();
        await page.locator('[data-estado="vacio"]').waitFor();
        assert.match(await panel.innerText(), /Todavía no existen/);
        cuerpo = { success: true, data: {} };
        await page.reload();
        await page.locator('#estadoVacioEvaluaciones[data-estado="error"]').waitFor();
        assert.equal((await panel.innerText()).includes('Todavía no'), false);
        for (const codigo of [400, 404, 409]) {
            estado = codigo;
            await page.reload();
            await page.locator('#estadoVacioEvaluaciones[data-estado="error"]').waitFor();
            assert.equal(await page.locator('.boton-reintentar').count(), 0);
        }
        estado = 200;
        cuerpo = { success: true, data: { total: 1, items: [{
            alerta_id: 'alerta-sintetica', box: 'box-1', tipo_riesgo: 'riesgo_suicida',
            nivel_severidad: 1, fecha_hora: '2026-09-12T15:00:00Z',
            estado_evaluacion: 'correcta', evaluacion: { evaluacion: 'correcta' },
        }] } };
        await page.reload();
        await page.locator('#tablaEvaluacionesContenedor').waitFor();
        assert.equal(await page.locator('#tablaEvaluaciones tr').count(), 1);
        estado = 503;
        await page.reload();
        await page.locator('#estadoVacioEvaluaciones[data-estado="error"]').waitFor();
        assert.equal(await page.locator('#tablaEvaluacionesContenedor').isVisible(), false, 'no presenta datos anteriores como actuales');

        estado = 200;
        const alertaPrueba = {
            ...cuerpo.data.items[0], alerta_id: '33333333-3333-4333-8333-000000000001',
            es_prueba: true, estado_evaluacion: 'pendiente', evaluacion: null,
        };
        await page.route(`**/api/v1/alerts/${alertaPrueba.alerta_id}`, route =>
            route.fulfill({ json: { success: true, data: alertaPrueba } }));
        await page.route(`**/api/v1/alerts/${alertaPrueba.alerta_id}/evaluacion`, route => {
            assert.equal(route.request().method(), 'POST');
            assert.deepEqual(route.request().postDataJSON(), { evaluacion: 'correcta' });
            alertaPrueba.estado_evaluacion = 'correcta';
            alertaPrueba.evaluacion = {
                alerta_id: alertaPrueba.alerta_id, evaluacion: 'correcta', estado_evaluacion: 'correcta',
                usuario: 'supervisor-sintetico', fecha_hora: '2026-09-12T15:10:00Z',
            };
            return route.fulfill({ status: 201, json: { success: true, data: alertaPrueba.evaluacion } });
        });
        registros = [alertaPrueba];
        await page.getByRole('button', { name: 'Actualizar', exact: true }).click();
        const filaPrueba = page.locator('#tablaEvaluaciones tr').first();
        await filaPrueba.getByText('Alerta de prueba', { exact: true }).waitFor();
        assert.equal(await filaPrueba.getByText('Pendiente', { exact: true }).isVisible(), true);
        await filaPrueba.getByRole('button').click();
        const detallePrueba = page.getByRole('dialog');
        await detallePrueba.getByText('Alerta de prueba', { exact: true }).waitFor();
        await detallePrueba.getByRole('radio', { name: /escenario simulado/ }).check();
        await detallePrueba.getByRole('button', { name: 'Guardar evaluación' }).click();
        const confirmacionPrueba = detallePrueba.locator('#estadoDetalle [data-estado="exito"]');
        await confirmacionPrueba.waitFor();
        assert.equal(await confirmacionPrueba.innerText(), 'Evaluación registrada.');
        await detallePrueba.getByRole('button', { name: 'Cerrar' }).click();
        await filaPrueba.getByText('Revisada', { exact: true }).waitFor();
        assert.equal(await filaPrueba.getByText('Alerta de prueba', { exact: true }).isVisible(), true);

        const anterior = page.locator('#evaluacionesAnterior');
        const siguiente = page.locator('#evaluacionesSiguiente');
        const filas = page.locator('#tablaEvaluaciones tr');
        for (const [total, ancho] of [[100, 1366], [500, 320]]) {
            registros = Array.from({ length: total }, (_, index) => ({
                ...cuerpo.data.items[0],
                alerta_id: `33333333-3333-4333-8333-${String(index + 1).padStart(12, '0')}`,
            }));
            await page.setViewportSize({ width: ancho, height: 800 });
            await page.reload();
            await filas.first().waitFor();
            assert.equal(await anterior.isDisabled(), true);
            assert.equal(await filas.first().locator('td').count(), 6);
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth),
                true, `sin desplazamiento horizontal de la página a ${ancho}px`);
            const accion = filas.first().getByRole('button');
            const visible = await accion.evaluate(boton => {
                const tabla = boton.closest('.ui-table-scroll');
                const marco = tabla.getBoundingClientRect();
                const accion = boton.getBoundingClientRect();
                return tabla.scrollLeft === 0 && accion.left >= marco.left && accion.right <= marco.right
                    && accion.width >= 44 && accion.height >= 44;
            });
            assert.equal(visible, true, 'acción visible sin desplazar la tabla y con área táctil suficiente');

            const visibles = [];
            const paginas = Math.ceil(total / 10);
            for (let pagina = 1; pagina <= paginas; pagina++) {
                await page.getByText(`Página ${pagina} de ${paginas}`, { exact: true }).waitFor();
                assert.equal(await filas.count(), 10);
                visibles.push(...await filas.locator('button').evaluateAll(botones => botones.map(boton => boton.dataset.alerta)));
                if (pagina < paginas) await siguiente.click();
            }
            assert.deepEqual(visibles, registros.map(alerta => alerta.alerta_id));
            assert.equal(await siguiente.isDisabled(), true);
            assert.equal(await page.locator('#resultadoEvaluaciones').innerText(), `Mostrando ${total - 9}–${total} de ${total} registros`);
            await anterior.click();
            await page.getByText(`Página ${paginas - 1} de ${paginas}`, { exact: true }).waitFor();
            console.log(`Registro de evaluaciones: ${total} registros, ${paginas} páginas sin duplicados a ${ancho}px.`);
        }
        await page.setViewportSize({ width: 1280, height: 720 });
        registros = undefined;
        estado = 401;
        await page.reload();
        await page.waitForURL(`${base}/`);
        assert.equal(await page.evaluate(() => localStorage.getItem('access_token')), null);

        const alerta = { ...cuerpo.data.items[0], estado_evaluacion: 'pendiente', evaluacion: null };
        let evaluacion = null;
        let estadoEvaluacion = 503;
        const consultasHistorial = [];
        await page.route('**/api/v1/alerts**', async route => {
            const url = new URL(route.request().url());
            let data;
            if (url.pathname.endsWith('/evaluacion')) {
                assert.equal(route.request().method(), 'POST');
                assert.equal(route.request().postDataJSON().evaluacion, 'correcta');
                if (estadoEvaluacion !== 200) return route.fulfill({ status: estadoEvaluacion });
                evaluacion = { alerta_id: alerta.alerta_id, evaluacion: 'correcta', estado_evaluacion: 'correcta',
                    usuario: 'supervisor-sintetico', fecha_hora: '2026-10-27T15:00:00Z' };
                data = evaluacion;
            } else if (url.pathname.endsWith('/' + alerta.alerta_id)) {
                data = { ...alerta, ...(evaluacion ? { evaluacion, estado_evaluacion: 'correcta' } : {}) };
            } else {
                if (url.searchParams.get('limit') === '10') consultasHistorial.push(url.searchParams);
                const items = url.searchParams.has('q') ? [] : [alerta];
                data = { items, total: items.length, limit: Number(url.searchParams.get('limit') || 10), offset: 0 };
            }
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) });
        });
        await page.goto(`${base}/dashboard`);
        await page.locator('[data-alerta]').first().waitFor();
        const buscar = page.locator('#buscar');
        const sinResultados = page.locator('#estadoVacio[data-estado="vacio"]');
        const consultasIniciales = consultasHistorial.length;
        await buscar.fill('sin');
        await page.waitForTimeout(400);
        await buscar.fill('sin coincidencias');
        await page.waitForTimeout(400);
        assert.equal(consultasHistorial.length, consultasIniciales, 'escribir texto no consulta el historial');
        await buscar.press('Enter');
        await sinResultados.waitFor();
        assert.equal(consultasHistorial.length, consultasIniciales + 1);
        assert.equal(consultasHistorial.at(-1).get('q'), 'sin coincidencias');

        await buscar.fill('texto sin confirmar');
        await Promise.all([
            page.waitForResponse(response => new URL(response.url()).searchParams.get('box') === 'box-3'),
            page.locator('#filtroBox').selectOption('box-3'),
        ]);
        await sinResultados.waitFor();
        assert.equal(consultasHistorial.at(-1).get('box'), 'box-3');
        assert.equal(consultasHistorial.at(-1).get('q'), 'sin coincidencias', 'el filtro aplica la última búsqueda confirmada');
        await Promise.all([
            page.waitForResponse(response => new URL(response.url()).searchParams.get('q') === 'sin coincidencias'),
            page.locator('#botonActualizar').click(),
        ]);
        await sinResultados.waitFor();
        assert.equal(consultasHistorial.at(-1).get('q'), 'sin coincidencias');
        assert.equal(await buscar.inputValue(), 'texto sin confirmar');
        await Promise.all([
            page.waitForResponse(response => new URL(response.url()).searchParams.get('q') === 'texto sin confirmar'),
            page.getByRole('search', { name: 'Buscar alertas' }).getByRole('button', { name: 'Buscar', exact: true }).click(),
        ]);
        await sinResultados.waitFor();
        assert.equal(consultasHistorial.at(-1).get('q'), 'texto sin confirmar');
        assert.match(await page.locator('#estadoVacio').innerText(), /filtros/);
        await page.locator('#limpiarFiltros').click();
        await page.locator('[data-alerta]').first().click();
        assert.equal(consultasHistorial.at(-1).has('q'), false);
        assert.equal(await buscar.inputValue(), '');
        const guardar = page.locator('#guardarEvaluacion');
        await guardar.waitFor();

        const radioConFoco = page.locator('input[name="evaluacion"]:focus');
        const cerrar = page.getByRole('dialog').getByRole('button', { name: 'Cerrar', exact: true });
        await cerrar.focus();
        await page.keyboard.press('Tab');
        assert.equal(await radioConFoco.inputValue(), 'correcta');
        await page.keyboard.press('Tab');
        assert.equal(await guardar.evaluate(boton => boton === document.activeElement), true);
        assert.equal(await page.locator('input[name="evaluacion"]:checked').count(), 0);
        await guardar.click();
        await page.locator('#mensajeEvaluacion[role="alert"]').waitFor();
        await page.locator('input[name="evaluacion"][value="correcta"]').check();
        await page.keyboard.press('ArrowRight');
        assert.equal(await page.locator('input[name="evaluacion"][value="falso_positivo"]').isChecked(), true);
        await cerrar.focus();
        await page.keyboard.press('Tab');
        assert.equal(await radioConFoco.inputValue(), 'falso_positivo');
        await page.keyboard.press('ArrowLeft');
        await guardar.click();
        await page.getByText('El servicio no está disponible temporalmente.', { exact: false }).waitFor();
        assert.equal(await page.locator('input[name="evaluacion"][value="correcta"]').isChecked(), true);
        estadoEvaluacion = 200;
        await guardar.click();
        await page.locator('#evaluacionRegistrada').waitFor();
        assert.equal(await page.locator('#evaluacionRegistrada').isVisible(), true);
        assert.deepEqual(errores, [], 'sin errores JavaScript en las pantallas');
        console.log('Integración verificada: login, carga, reintento, estados HTTP, sesión, filtros y selección.');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });

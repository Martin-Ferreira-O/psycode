// Prueba de integración opcional: requiere Playwright y el servidor Django local.
const assert = require('node:assert/strict');
const { join } = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
    });
    const page = await browser.newPage();
    const base = process.env.FRONTEND_TEST_URL || 'http://127.0.0.1:8765';
    const registrosPorPagina = 12;
    const errores = [];
    page.on('pageerror', e => errores.push(e.message));
    let estado = 503;
    let peticiones = 0;
    let consultasRegistro = 0;
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
            const parametros = new URL(route.request().url()).searchParams;
            if (parametros.get('limit') === '1') {
                const data = registros ? { items: registros, total: registros.length } : cuerpo.data;
                const snapshot = data?.items ? { items: data.items.slice(0, 1), total: data.total } : data;
                return route.fulfill({ status: estado, json: { success: true, data: snapshot } });
            }
            consultasRegistro++;
            if (liberar === null) {
                await new Promise(resolve => {
                    liberar = resolve;
                    confirmarConsulta();
                });
            }
            let respuesta = cuerpo;
            if (registros) {
                const limit = Number(parametros.get('limit'));
                const offset = Number(parametros.get('offset'));
                const filtro = parametros.get('estado_evaluacion');
                const coincidencias = filtro
                    ? registros.filter(registro => registro.estado_evaluacion === filtro)
                    : registros;
                assert.equal(limit, registrosPorPagina);
                respuesta = { success: true, data: {
                    items: coincidencias.slice(offset, offset + limit), total: coincidencias.length, limit, offset,
                } };
            }
            await route.fulfill({ status: estado, contentType: 'application/json', body: JSON.stringify(respuesta) });
        });
        await page.goto(`${base}/evaluaciones`);
        const panel = page.locator('#estadoVacioEvaluaciones');
        await page.locator('#tablaEvaluacionesContenedor .ui-skeleton').first().waitFor();
        assert.equal(await page.getByRole('heading', { name: 'Registro de evaluaciones' }).isVisible(), true);
        assert.equal(await page.getByRole('columnheader', { name: 'Fecha' }).isVisible(), true);
        assert.equal(await page.getByRole('button', { name: 'Tabla', exact: true }).getAttribute('aria-pressed'), 'true');
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
        alertaPrueba.analisis = { categoria: "Ideación con alguna intención", nivel_matriz: 4, plazo: "mañana", inicio: 2, fin: 3, puntaje: .9, umbral: .4, version: "bloque-signals-6" };
        let transcripcion = 'Fragmento redactado de la prueba de audio.';
        await page.route(`**/api/v1/alerts/${alertaPrueba.alerta_id}`, route =>
            route.fulfill({ json: { success: true, data: { ...alertaPrueba, descripcion: transcripcion } } }));
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
        assert.equal(await filaPrueba.getByText('Detección', { exact: true }).isVisible(), true);
        assert.doesNotMatch(await filaPrueba.innerText(), /33333333-3333/);
        const vistaTarjetas = page.getByRole('button', { name: 'Tarjetas', exact: true });
        const vistaTabla = page.getByRole('button', { name: 'Tabla', exact: true });
        const tarjeta = page.getByRole('article');
        const consultasAntesDelCambio = consultasRegistro;
        await vistaTarjetas.press('Enter');
        assert.equal(await vistaTarjetas.getAttribute('aria-pressed'), 'true');
        assert.equal(await vistaTabla.getAttribute('aria-pressed'), 'false');
        assert.equal(await filaPrueba.count(), 0);
        assert.equal(consultasRegistro, consultasAntesDelCambio, 'cambiar la vista reutiliza la página consultada');
        assert.equal(await tarjeta.getByRole('heading', { name: 'Riesgo suicida' }).isVisible(), true);
        assert.equal(await tarjeta.getByText('Box 01', { exact: true }).isVisible(), true);
        assert.equal(await tarjeta.getByText('Pendiente', { exact: true }).isVisible(), true);
        assert.doesNotMatch(await tarjeta.innerText(), /33333333-3333/);
        await page.reload();
        const evaluarTarjeta = tarjeta.getByRole('button', { name: /^Evaluar/ });
        await evaluarTarjeta.press('Enter');
        await page.getByRole('dialog').getByText('Ideación con alguna intención', { exact: true }).waitFor();
        await page.getByText('Plazo expresado en la frase: mañana').waitFor();
        await page.getByRole('dialog').getByRole('button', { name: 'Cerrar' }).click();
        assert.equal(await evaluarTarjeta.evaluate(button => document.activeElement === button), true);
        await evaluarTarjeta.press('Enter');
        await page.getByRole('dialog').getByText('Ideación con alguna intención', { exact: true }).waitFor();
        await page.getByText('Plazo expresado en la frase: mañana').waitFor();
        const detallePrueba = page.getByRole('dialog');
        await detallePrueba.getByText('Alerta de prueba', { exact: true }).waitFor();
        assert.equal(await detallePrueba.getByText(/Hablante sin confirmar/).count(), 0);
        const verTranscripcion = detallePrueba.getByRole('button', { name: 'Ver transcripción' });
        const fragmento = detallePrueba.locator('#detalleTranscripcion');
        assert.equal(await verTranscripcion.getAttribute('aria-expanded'), 'false');
        assert.equal(await fragmento.isVisible(), false);
        await verTranscripcion.press('Enter');
        await fragmento.waitFor();
        assert.equal(await fragmento.innerText(), transcripcion);
        const ocultarTranscripcion = detallePrueba.getByRole('button', { name: 'Ocultar transcripción' });
        assert.equal(await ocultarTranscripcion.getAttribute('aria-expanded'), 'true');
        await ocultarTranscripcion.click();
        assert.equal(await fragmento.isVisible(), false);
        await detallePrueba.getByRole('radio', { name: /escenario simulado/ }).check();
        await detallePrueba.getByRole('button', { name: 'Guardar evaluación' }).click();
        const confirmacionPrueba = detallePrueba.locator('#estadoDetalle [data-estado="exito"]');
        await confirmacionPrueba.waitFor();
        assert.equal(await confirmacionPrueba.innerText(), 'Evaluación registrada.');
        await detallePrueba.getByRole('button', { name: 'Cerrar' }).click();
        await tarjeta.getByText('Correcta', { exact: true }).waitFor();
        assert.equal(await tarjeta.getByText('Evaluación', { exact: true }).isVisible(), true);
        assert.equal(await tarjeta.locator('time').getAttribute('datetime'), alertaPrueba.evaluacion.fecha_hora);
        await vistaTabla.click();
        await filaPrueba.getByText('Correcta', { exact: true }).waitFor();
        assert.equal(await filaPrueba.getByText('Alerta de prueba', { exact: true }).isVisible(), true);
        transcripcion = null;
        await filaPrueba.getByRole('button').click();
        await verTranscripcion.click();
        assert.match(await fragmento.innerText(), /no tiene un fragmento de transcripción disponible/);
        await detallePrueba.getByRole('button', { name: 'Cerrar' }).click();

        const anterior = page.locator('#evaluacionesAnterior');
        const siguiente = page.locator('#evaluacionesSiguiente');
        const filas = page.locator('#tablaEvaluaciones tr');
        for (const [total, ancho] of [[52, 1920], [100, 1366], [500, 320]]) {
            registros = Array.from({ length: total }, (_, index) => ({
                ...cuerpo.data.items[0],
                alerta_id: `33333333-3333-4333-8333-${String(index + 1).padStart(12, '0')}`,
            }));
            await page.setViewportSize({ width: ancho, height: 800 });
            await page.reload();
            await filas.first().waitFor();
            if (total === 52) {
                await vistaTarjetas.click();
                const tarjetasPorFila = await tarjeta.evaluateAll(tarjetas =>
                    Array.from(Map.groupBy(tarjetas, item => item.getBoundingClientRect().top).values(), fila => fila.length));
                assert.deepEqual(tarjetasPorFila, [4, 4, 4]);
                assert.equal(await page.locator('#resultadoEvaluaciones').innerText(), 'Mostrando 1–12 de 52 registros');
                await vistaTabla.click();
            }
            assert.equal(await anterior.isDisabled(), true);
            assert.equal(await filas.first().locator('td').count(), 4);
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
            const paginas = Math.ceil(total / registrosPorPagina);
            for (let pagina = 1; pagina <= paginas; pagina++) {
                await page.getByText(`Página ${pagina} de ${paginas}`, { exact: true }).waitFor();
                assert.equal(await filas.count(), Math.min(registrosPorPagina, total - (pagina - 1) * registrosPorPagina));
                visibles.push(...await filas.locator('button').evaluateAll(botones => botones.map(boton => boton.dataset.alerta)));
                if (pagina < paginas) await siguiente.click();
            }
            assert.deepEqual(visibles, registros.map(alerta => alerta.alerta_id));
            assert.equal(await siguiente.isDisabled(), true);
            const primerRegistroUltimaPagina = (paginas - 1) * registrosPorPagina + 1;
            assert.equal(await page.locator('#resultadoEvaluaciones').innerText(), `Mostrando ${primerRegistroUltimaPagina}–${total} de ${total} registros`);
            await anterior.click();
            await page.getByText(`Página ${paginas - 1} de ${paginas}`, { exact: true }).waitFor();
            const registrosEnTabla = await filas.locator('button').evaluateAll(botones => botones.map(boton => boton.dataset.alerta));
            await vistaTarjetas.click();
            assert.deepEqual(await tarjeta.locator('[data-alerta]').evaluateAll(botones => botones.map(boton => boton.dataset.alerta)), registrosEnTabla);
            assert.equal(await page.getByText(`Página ${paginas - 1} de ${paginas}`, { exact: true }).isVisible(), true);
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), true);
            await vistaTabla.click();
            console.log(`Registro de evaluaciones: ${total} registros, ${paginas} páginas sin duplicados a ${ancho}px.`);
        }
        await page.setViewportSize({ width: 375, height: 800 });
        registros = registros.map((registro, index) => index % 40 === 0 ? registro : {
            ...registro, estado_evaluacion: 'falso_positivo', evaluacion: { evaluacion: 'falso_positivo' },
        });
        const filtroEvaluaciones = page.getByRole('combobox', { name: 'Filtrar evaluaciones por estado' });
        await filtroEvaluaciones.focus();
        await filtroEvaluaciones.selectOption('correcta');
        await page.getByText('Página 1 de 2', { exact: true }).waitFor();
        assert.equal(await page.locator('#resultadoEvaluaciones').innerText(), 'Mostrando 1–12 de 13 registros');
        assert.equal(await filas.getByText('Correcta', { exact: true }).count(), registrosPorPagina);
        assert.equal(await filtroEvaluaciones.evaluate(select => document.activeElement === select), true);
        await siguiente.click();
        await page.getByText('Página 2 de 2', { exact: true }).waitFor();
        await vistaTarjetas.click();
        assert.equal(await tarjeta.getByText('Correcta', { exact: true }).count(), 1);
        assert.equal(await filtroEvaluaciones.inputValue(), 'correcta');
        await filtroEvaluaciones.selectOption('neutro');
        await page.getByText('No hay registros que coincidan con el estado seleccionado.').waitFor();
        await filtroEvaluaciones.selectOption('');
        await page.getByText('Página 1 de 42', { exact: true }).waitFor();
        assert.equal(await page.locator('#resultadoEvaluaciones').innerText(), 'Mostrando 1–12 de 500 registros');
        await page.evaluate(() => localStorage.removeItem('evaluaciones.vista'));
        await page.clock.install();
        const consultaInicial = page.waitForResponse(response => {
            const url = new URL(response.url());
            return url.pathname === '/api/v1/alerts' && url.searchParams.get('limit') === '1';
        });
        await page.reload();
        await tarjeta.first().waitFor();
        await consultaInicial;
        assert.equal(await vistaTarjetas.getAttribute('aria-pressed'), 'true');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth), true);

        const avisoNuevoRegistro = page.locator('.evaluation-toast');
        assert.equal(await avisoNuevoRegistro.innerText(), '', 'la consulta inicial no genera avisos');
        await filtroEvaluaciones.selectOption('correcta');
        await siguiente.click();
        await page.getByText('Página 2 de 2', { exact: true }).waitFor();
        await filtroEvaluaciones.focus();
        const panelAntesDelAviso = await page.locator('.panel-evaluaciones').boundingBox();
        const consultasAntesDelAviso = consultasRegistro;
        registros.unshift({ ...registros[0], alerta_id: 'registro-recien-incorporado', estado_evaluacion: 'pendiente', es_prueba: true, evaluacion: null });
        await page.clock.fastForward(15_000);
        const contenidoDelAviso = avisoNuevoRegistro.getByRole('status');
        await contenidoDelAviso.getByText(/Actualizaremos la lista/).waitFor();
        assert.deepEqual(await page.locator('.panel-evaluaciones').boundingBox(), panelAntesDelAviso, 'la notificación flotante no mueve el listado');
        assert.equal(await avisoNuevoRegistro.evaluate(toast => getComputedStyle(toast).pointerEvents), 'none');
        assert.equal(consultasRegistro, consultasAntesDelAviso, 'avisa antes de volver a consultar la página');
        await page.clock.fastForward(1_500);
        await contenidoDelAviso.getByText(/está al día/).waitFor();
        assert.equal(consultasRegistro, consultasAntesDelAviso + 1);
        assert.equal(await filtroEvaluaciones.evaluate(select => document.activeElement === select && select.value === 'correcta'), true);
        assert.equal(await page.getByText('Página 2 de 2', { exact: true }).isVisible(), true);
        await avisoNuevoRegistro.locator('.evaluation-toast-time > span').evaluate(barra => barra.getAnimations()[0].finish());
        await contenidoDelAviso.getByText('Nueva alerta en evaluaciones').waitFor({ state: 'hidden' });
        await page.clock.fastForward(15_000);
        assert.equal(await avisoNuevoRegistro.innerText(), '', 'no vuelve a anunciar el mismo registro');

        const consultasAntesDeCerrar = consultasRegistro;
        registros.unshift({ ...registros[0], alerta_id: 'otro-registro-recien-incorporado' });
        await page.clock.fastForward(15_000);
        await contenidoDelAviso.getByText(/Actualizaremos la lista/).waitFor();
        await anterior.focus();
        await page.keyboard.press('Tab');
        const cerrarAviso = avisoNuevoRegistro.getByRole('button', { name: 'Cerrar notificación de nueva alerta' });
        assert.equal(await cerrarAviso.evaluate(button => document.activeElement === button), true);
        assert.equal(await avisoNuevoRegistro.locator('.evaluation-toast-time > span').evaluate(barra => getComputedStyle(barra).animationPlayState), 'paused');
        await page.keyboard.press('Enter');
        await cerrarAviso.waitFor({ state: 'hidden' });
        assert.equal(await anterior.evaluate(button => document.activeElement === button), true);
        const recargaDespuesDeCerrar = page.waitForResponse(response => {
            const url = new URL(response.url());
            return url.pathname === '/api/v1/alerts' && url.searchParams.get('limit') === '12';
        });
        await page.clock.fastForward(1_500);
        await recargaDespuesDeCerrar;
        assert.equal(consultasRegistro, consultasAntesDeCerrar + 1, 'cerrar el aviso deja que el registro se actualice');
        assert.equal(await avisoNuevoRegistro.innerText(), '', 'la actualización no vuelve a abrir el aviso cerrado');

        await page.setViewportSize({ width: 1280, height: 720 });
        registros = undefined;
        estado = 401;
        await page.reload();
        await page.waitForURL(`${base}/`);
        assert.equal(await page.evaluate(() => localStorage.getItem('access_token')), null);

        const alerta = { ...cuerpo.data.items[0], estado_evaluacion: 'pendiente', evaluacion: null };
        let evaluacion = null;
        let estadoEvaluacion = 503;
        let estadoDetalle = 503;
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
                if (estadoDetalle !== 200) return route.fulfill({ status: estadoDetalle });
                data = { ...alerta, hablante_no_confirmado: true, descripcion: 'Afirmación de prueba.' };
                if (evaluacion) Object.assign(data, { evaluacion, estado_evaluacion: 'correcta' });
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
        await page.locator('[data-alerta]').first().press('Enter');
        assert.equal(consultasHistorial.at(-1).has('q'), false);
        assert.equal(await buscar.inputValue(), '');
        const detalle = page.getByRole('dialog');
        const avisoHablante = detalle.getByText(/Hablante sin confirmar/);
        await detalle.getByRole('alert').waitFor();
        assert.equal(await avisoHablante.count(), 0);
        estadoDetalle = 200;
        await detalle.getByRole('button', { name: 'Reintentar', exact: true }).press('Enter');
        await avisoHablante.waitFor();
        assert.equal(await detalle.locator('#detalleTranscripcion').innerText(), 'Afirmación de prueba.');
        for (const width of [375, 1280]) {
            await page.setViewportSize({ width, height: 720 });
            assert.equal(await detalle.evaluate(dialog => dialog.scrollWidth === dialog.clientWidth), true);
            assert.equal(await avisoHablante.isVisible(), true);
            if (process.env.FRONTEND_SCREENSHOT_DIR) {
                await detalle.screenshot({ path: join(process.env.FRONTEND_SCREENSHOT_DIR, `hablante-sin-confirmar-${width}.png`) });
            }
        }
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

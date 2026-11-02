// Bitácora real con eventos sintéticos: no conecta MongoDB ni envía mensajes.
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { join } = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
    const browser = await chromium.launch({ headless: true,
        ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) });
    const page = await browser.newPage({ viewport: { width: 1366, height: 950 } });
    const base = process.env.FRONTEND_TEST_URL || 'http://127.0.0.1:8765';
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const alertId = randomUUID(), notificationId = randomUUID();
    const historic = { event_id: randomUUID(), timestamp: new Date().toISOString(),
        action: 'notifications.send', outcome: 'success', actor_id: null,
        alerta_id: alertId, sesion_id: null, sequence: null, channel: 'email',
        contingencia: null, error_code: null, duration_ms: 5 };
    const summary = { ...historic, event_id: randomUUID(), action: 'notifications.result',
        outcome: 'failure', contingencia: true, duration_ms: null,
        notification: { id: notificationId, mode: 'supervisores_activos', phase: 'resumen',
            reason: 'FALLO_PARCIAL', status: 'FALLO_PARCIAL', primary_successes: 2,
            primary_failures: 1, backup_successes: 1, backup_failures: 0 } };
    const backup = { ...historic, event_id: randomUUID(), contingencia: true,
        notification: { id: notificationId, mode: 'supervisores_activos', phase: 'respaldo',
            attempt: 4, reason: 'FALLO_PARCIAL' } };
    const missing = { ...summary, event_id: randomUUID(), outcome: 'skipped', contingencia: false,
        notification: { ...summary.notification, id: randomUUID(), mode: null,
            status: 'SIN_DESTINATARIOS_VALIDOS', reason: 'SIN_DESTINATARIOS_VALIDOS',
            primary_successes: 0, primary_failures: 0, backup_successes: 0 } };
    const events = [summary, backup, historic, missing];
    try {
        await page.addInitScript(() => localStorage.setItem('access_token', 'token-sintetico'));
        await page.route('**/api/v1/auth/me', route => route.fulfill({
            json: { success: true, data: { usuario: 'admin-prueba', rol: 'admin' } } }));
        await page.route('**/api/v1/audit-events**', route => {
            const params = new URL(route.request().url()).searchParams;
            const filtered = events.filter(event => ['action', 'outcome', 'alerta_id'].every(
                key => !params.get(key) || event[key] === params.get(key)));
            const offset = Number(params.get('offset') || 0), limit = Number(params.get('limit') || 50);
            return route.fulfill({ json: { success: true, data: {
                items: filtered.slice(offset, offset + limit), total: filtered.length, offset, limit } } });
        });
        await page.goto(`${base}/bitacora`);
        await page.locator('#tablaEventos tr').first().waitFor();
        assert.equal(await page.locator('#tablaEventos tr').count(), 4);
        assert.equal(await page.locator('.resumen-bitacora .tarjeta-resumen').count(), 7);
        assert.equal(await page.locator('select#filtroAccion').count(), 1);
        assert.equal(await page.locator('.cabecera-dashboard h1').innerText(), 'Bitácora del sistema');
        assert.match(await page.locator('#tablaEventos tr').first().innerText(), /Resumen.*Fallo parcial/s);
        const summaryBadge = page.locator('#tablaEventos tr').first().locator('.etiqueta-evento');
        assert.equal(await summaryBadge.innerText(), 'Resumen de notificación');
        assert.equal(await summaryBadge.getAttribute('title'), 'Resumen de notificación');
        const missingBadge = page.locator('#tablaEventos tr').nth(3).locator('.etiqueta-resultado');
        assert.equal(await missingBadge.innerText(), 'Sin destinatarios válidos');
        assert.equal(await missingBadge.getAttribute('title'), 'Sin destinatarios válidos');
        const checkBadges = async () => {
            const overflows = await page.locator('.etiqueta-evento, .etiqueta-resultado, .etiqueta-canal').evaluateAll(labels =>
                labels.filter(label => {
                    const range = document.createRange();
                    range.selectNodeContents(label);
                    const text = range.getBoundingClientRect();
                    const badge = label.getBoundingClientRect();
                    return text.left < badge.left - 1 || text.right > badge.right + 1 ||
                        text.top < badge.top - 1 || text.bottom > badge.bottom + 1;
                }).map(label => label.textContent)
            );
            assert.deepEqual(overflows, [], 'las etiquetas contienen su texto sin recortarlo');
        };
        await checkBadges();
        if (process.env.FRONTEND_SCREENSHOT_DIR) {
            await page.locator('#contenedorTabla').screenshot({
                path: join(process.env.FRONTEND_SCREENSHOT_DIR, 'bitacora-etiquetas.png') });
        }
        await page.locator('#tablaEventos tr').first().getByRole('button').click();
        const detail = page.locator('#detalleNotificacion');
        await detail.waitFor({ state: 'visible' });
        assert.equal(await page.locator('#detalleAccion').innerText(), 'Resumen de notificación');
        for (const text of ['Supervisores activos', '2 éxitos · 1 fallo', '1 éxito · 0 fallos',
                            'Fallo parcial del envío principal', notificationId]) {
            assert.ok((await detail.innerText()).includes(text), text);
        }
        assert.equal(await page.locator('#detalleContingencia').innerText(), 'Sí');
        await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
        await page.locator('#copiarAlerta').click();
        assert.equal(await page.evaluate(() => navigator.clipboard.readText()), alertId);
        await page.locator('#cerrarDetalle').focus();
        await page.keyboard.press('Shift+Tab');
        assert.ok(await page.locator('#copiarEvento').evaluate(el => el === document.activeElement));
        await page.keyboard.press('Tab');
        assert.ok(await page.locator('#cerrarDetalle').evaluate(el => el === document.activeElement));
        if (process.env.FRONTEND_SCREENSHOT_DIR) {
            await detail.scrollIntoViewIfNeeded();
            await page.locator('#panelDetalle').screenshot({
                path: join(process.env.FRONTEND_SCREENSHOT_DIR, 'bitacora-resumen.png') });
        }
        await page.keyboard.press('Escape');
        await page.locator('#tablaEventos tr').nth(1).getByRole('button').click();
        assert.ok((await detail.innerText()).includes('Envío de respaldo'));
        assert.ok((await detail.textContent()).includes('Número de intento'));
        assert.ok(!(await detail.textContent()).includes('Envíos principales'));
        await page.keyboard.press('Escape');
        await page.locator('#tablaEventos tr').nth(2).getByRole('button').click();
        assert.equal(await detail.isVisible(), false);
        assert.equal(await page.locator('#detalleContingencia').innerText(), 'No registrado');
        assert.equal(await page.locator('#detalleActor').innerText(), 'Sistema');
        await page.keyboard.press('Escape');
        await page.locator('#filtroAccion').selectOption('notifications.result');
        await page.locator('#formFiltros').evaluate(form => form.requestSubmit());
        await page.waitForFunction(() => document.querySelectorAll('#tablaEventos tr').length === 2);
        await page.locator('#tablaEventos tr').nth(1).getByRole('button').click();
        assert.match(await page.locator('#detalleResultado').innerText(), /Sin destinatarios válidos/);
        assert.ok((await detail.innerText()).includes('0 éxitos · 0 fallos'));
        await page.keyboard.press('Escape');
        await page.setViewportSize({ width: 390, height: 844 });
        await checkBadges();
        await page.locator('#tablaEventos tr').first().getByRole('button').click();
        await page.locator('#panelDetalle').evaluate(async panel => {
            await Promise.all(panel.getAnimations().map(animation => animation.finished));
        });
        const bounds = await page.locator('#panelDetalle').boundingBox();
        assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 391, JSON.stringify(bounds));

        // SCRUM-86: presentación del nombre del actor.
        const usuarioId = randomUUID(), eliminadoId = randomUUID();
        const historicoId = randomUUID(), sinActorId = randomUUID();
        const maliciosoId = randomUUID();
        const nombreUsuario = 'Ana & José';
        const textoMalicioso = '<img src=x onerror=alert(1)>';
        const eventosActores = [
            { ...historic, event_id: randomUUID(), actor_id: usuarioId,
                actor: nombreUsuario },
            { ...historic, event_id: randomUUID(), actor_id: null,
                actor: 'Sistema' },
            { ...historic, event_id: randomUUID(), actor_id: eliminadoId,
                actor: `Usuario (${eliminadoId})` },
            { ...historic, event_id: randomUUID(), actor_id: historicoId,
                actor: 'Usuario' },
            { ...historic, event_id: randomUUID(), actor_id: sinActorId },
            { ...historic, event_id: randomUUID(), actor_id: maliciosoId,
                actor: textoMalicioso }
        ];
        events.splice(0, events.length, ...eventosActores);
        await page.setViewportSize({ width: 1366, height: 950 });
        await page.goto(`${base}/bitacora`);
        await page.waitForFunction(() => document.querySelectorAll('#tablaEventos tr').length === 6);
        assert.equal(await page.locator('#tablaEventos tr').count(), 6);
        const casos = [
            [nombreUsuario, `${nombreUsuario} · ${usuarioId}`],
            ['Sistema', 'Sistema'],
            [`Usuario (${eliminadoId})`, `Usuario (${eliminadoId})`],
            [`Usuario (${historicoId})`, `Usuario (${historicoId})`],
            [`Usuario (${sinActorId})`, `Usuario (${sinActorId})`],
            [textoMalicioso, `${textoMalicioso} · ${maliciosoId}`]
        ];
        for (const [indice, [textoTabla, textoDetalle]] of casos.entries()) {
            const fila = page.locator('#tablaEventos tr').nth(indice);
            const celdaActor = fila.locator('td').nth(3);
            assert.equal((await celdaActor.getAttribute("aria-label")) || (await celdaActor.textContent()), textoTabla,
                `Actor incorrecto en la tabla, fila ${indice}`);
            await fila.getByRole('button').click();
            assert.equal(await page.locator('#detalleActor').textContent(), textoDetalle,
                `Actor incorrecto en el detalle, fila ${indice}`);
            await page.keyboard.press('Escape');
        }
        assert.equal(await page.locator('#tablaEventos img, #detalleActor img').count(), 0);
        assert.equal(await page.locator('#tablaEventos tr').first()
            .locator('td').nth(3).textContent(), 'Ana & José');
        assert.deepEqual(errors, []);
        console.log('OK: diseño general original, tabla y detalle renovados, copia, foco, notificaciones, filtro, históricos y móvil.');
        console.log('OK SCRUM-86: nombres de usuario, Sistema, UUID de respaldo y texto seguro.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

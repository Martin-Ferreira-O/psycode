// Prueba sobre servidor local con fixtures sintéticos, aislado de datos reales.
// Ver docs/CONSERVACION-Y-ALMACENAMIENTO.md. Requiere Playwright y Chromium.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium' });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const base = process.env.FRONTEND_TEST_URL || 'http://127.0.0.1:8766';
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
        await page.goto(base);
        const login = await page.evaluate(async () => {
            const csrf = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).slice(10);
            return (await fetch('/api/v1/auth/login', { method: 'POST', headers: {
                'Content-Type': 'application/json', 'X-Psycode-Browser': '1', 'X-CSRFToken': csrf
            }, body: JSON.stringify({ usuario: 'storage-browser', password: 'Synthetic-browser-2026!' }) })).status;
        });
        assert.equal(login, 200);
        await page.goto(`${base}/configuracion-operativa/almacenamiento`);
        await page.locator('#datosAlmacenamiento:not([hidden])').waitFor();
        assert.match(await page.locator('#espacioProtegido').innerText(), /1 archivo/);
        await page.getByRole('button', { name: 'Liberar espacio', exact: true }).click();
        await page.getByRole('dialog').waitFor();
        assert.match(await page.locator('#resumenVistaPrevia').innerText(), /1 archivo/);
        await page.getByRole('button', { name: 'Cancelar', exact: true }).click();
        assert.equal(await page.getByRole('dialog').count(), 0);
        assert.equal(await page.locator('#vistaPreviaLimpieza').evaluate(x => x.open), false);
        await page.getByRole('button', { name: 'Liberar espacio', exact: true }).click();
        await page.getByRole('dialog').waitFor();
        await page.screenshot({ path: '/tmp/psycode-storage-preview.png', fullPage: true });
        await page.getByRole('button', { name: 'Confirmar limpieza', exact: true }).click();
        await page.locator('#estadoAlmacenamiento').filter({ hasText: /1 archivo eliminado/ }).waitFor();
        assert.match(await page.locator('#espacioLiberable').innerText(), /^0 B$/);
        assert.match(await page.locator('#espacioProtegido').innerText(), /1 archivo/);
        await page.screenshot({ path: '/tmp/psycode-storage-desktop.png', fullPage: true });
        // Fallo de transporte no habilita una confirmación sin vista previa.
        await page.route('**/api/v1/almacenamiento/vista-previa', route => route.fulfill({ status: 503, body: 'PRIVATE' }));
        await page.getByRole('button', { name: 'Liberar espacio', exact: true }).click();
        await page.locator('#estadoAlmacenamiento').filter({ hasText: /No se pudo/ }).waitFor();
        assert.equal(await page.locator('body').innerText().then(x => x.includes('PRIVATE')), false);
        assert.equal(await page.locator('#vistaPreviaLimpieza').evaluate(x => x.open), false);
        await page.setViewportSize({ width: 390, height: 844 });
        await page.screenshot({ path: '/tmp/psycode-storage-mobile.png', fullPage: true });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
        assert.deepEqual(errors, []);
        console.log('Almacenamiento: preview, cancelación, confirmación real, protecciones, error y responsive OK');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

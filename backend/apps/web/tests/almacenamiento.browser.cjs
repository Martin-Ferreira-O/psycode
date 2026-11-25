const assert = require('node:assert/strict');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const base = process.env.FRONTEND_TEST_URL || 'http://127.0.0.1:8766';
    const screenshots = process.env.FRONTEND_SCREENSHOT_DIR || tmpdir();
    const screenshot = name => page.screenshot({ path: join(screenshots, `psycode-storage-${name}.png`), fullPage: true });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
        await page.goto(base);
        await page.getByLabel('Correo institucional o usuario').fill('storage-browser');
        await page.getByLabel('Contraseña', { exact: true }).fill('Synthetic-browser-2026!');
        await page.getByRole('button', { name: 'Ingresar al sistema' }).click();
        await page.waitForURL('**/dashboard');

        await page.getByRole('link', { name: 'Configuración operativa' }).click();
        await page.getByRole('link', { name: 'Almacenamiento del servidor', exact: true }).click();
        await page.waitForURL('**/api/v1/almacenamiento/panel');

        const protegidos = page.getByText('Archivos protegidos', { exact: true }).locator('..').locator('dd');
        const liberables = page.getByText('Liberable ahora', { exact: true }).locator('..').locator('dd');
        const liberar = page.getByRole('button', { name: 'Liberar espacio', exact: true });
        const dialogo = page.getByRole('dialog', { name: 'Vista previa de limpieza' });
        await liberar.waitFor();
        assert.match(await protegidos.innerText(), /1 archivo/);

        await liberar.click();
        await dialogo.waitFor();
        assert.match(await dialogo.innerText(), /Se podrán liberar .* en 1 archivo/);
        const cancelar = dialogo.getByRole('button', { name: 'Cancelar', exact: true });
        assert.equal(await cancelar.evaluate(element => element === document.activeElement), true);
        await page.keyboard.press('Escape');
        await dialogo.waitFor({ state: 'hidden' });
        assert.equal(await liberar.evaluate(element => element === document.activeElement), true);

        await page.route('**/api/v1/almacenamiento/vista-previa', async route => {
            const response = await route.fetch();
            const body = await response.json();
            body.data.expires_in_seconds = 1;
            await route.fulfill({ response, json: body });
        }, { times: 1 });
        await liberar.click();
        await dialogo.getByRole('alert').filter({ hasText: /vista previa venció/ }).waitFor();
        assert.equal(await dialogo.getByRole('button', { name: 'Confirmar limpieza' }).isDisabled(), true);
        await dialogo.getByRole('button', { name: 'Cancelar' }).click();
        await dialogo.waitFor({ state: 'hidden' });

        await liberar.click();
        await dialogo.waitFor();
        await screenshot('preview');
        await dialogo.getByRole('button', { name: 'Confirmar limpieza', exact: true }).click();
        await page.getByRole('status').filter({ hasText: /1 archivo eliminado/ }).waitFor();
        await dialogo.waitFor({ state: 'hidden' });
        assert.match(await liberables.innerText(), /^0 B$/);
        assert.match(await protegidos.innerText(), /1 archivo/);
        await screenshot('desktop');

        await page.route('**/api/v1/almacenamiento/vista-previa', route => route.fulfill({ status: 503, body: 'PRIVATE' }));
        await liberar.click();
        await page.getByRole('alert').filter({ hasText: /No se pudo/ }).waitFor();
        assert.doesNotMatch(await page.locator('body').innerText(), /PRIVATE/);
        assert.equal(await dialogo.count(), 0);

        for (const width of [320, 390, 768, 1024, 1440]) {
            await page.setViewportSize({ width, height: 844 });
            await liberar.scrollIntoViewIfNeeded();
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `Desbordamiento a ${width}px`);
            assert.equal(await liberar.isVisible(), true);
            if (width === 390) await screenshot('mobile');
        }

        assert.deepEqual(errors, []);
        console.log('Almacenamiento: acceso, vista previa, cancelación, foco, vencimiento, confirmación real, protecciones, error y diseño responsive OK');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });

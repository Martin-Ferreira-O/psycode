// Intercepta la API para probar acceso y recuperación sin cuentas ni correo real.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
    });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const base = process.env.FRONTEND_TEST_URL || 'http://127.0.0.1:8765';
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    try {
        await page.route('**/api/v1/auth/password-reset', async route => {
            assert.deepEqual(route.request().postDataJSON(), { correo: 'cuenta@example.test' });
            assert.equal(route.request().headers()['x-psycode-browser'], '1');
            assert.ok(route.request().headers()['x-csrftoken']);
            await route.fulfill({ status: 202, json: { success: true, data: {} } });
        });
        await page.route('**/api/v1/auth/password-reset/confirm', async route => {
            assert.deepEqual(route.request().postDataJSON(), {
                token: 'token-sintetico',
                nueva_password: 'Clave-Sintetica-123!',
            });
            assert.equal(route.request().headers().referer, undefined);
            await route.fulfill({ json: { success: true, data: {} } });
        });

        await page.goto(base);
        const password = page.locator('#password');
        const reveal = page.getByRole('button', { name: 'Mostrar contraseña', exact: true });
        await reveal.click();
        assert.equal(await password.getAttribute('type'), 'text');
        await page.getByRole('button', { name: 'Ocultar contraseña', exact: true }).click();
        assert.equal(await password.getAttribute('type'), 'password');

        const recovery = page.getByRole('button', { name: '¿Olvidaste tu contraseña?' });
        await recovery.click();
        const dialog = page.getByRole('dialog', { name: 'Recuperar contraseña' });
        await dialog.waitFor();
        assert.equal(await dialog.locator('input:focus').count(), 1);
        await dialog.getByLabel('Correo institucional').fill('cuenta@example.test');
        await dialog.getByRole('button', { name: 'Enviar instrucciones' }).click();
        await dialog.getByText('Si el usuario existe', { exact: false }).waitFor();
        await page.keyboard.press('Escape');
        await dialog.waitFor({ state: 'hidden' });
        assert.equal(await recovery.evaluate(button => document.activeElement === button), true);

        for (const [width, height] of [[320, 568], [390, 844], [667, 375], [768, 1024], [1440, 900]]) {
            await page.setViewportSize({ width, height });
            const submit = page.getByRole('button', { name: 'Ingresar al sistema' });
            await submit.scrollIntoViewIfNeeded();
            assert.equal(await submit.isVisible(), true);
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, width);
            await recovery.click();
            const send = dialog.getByRole('button', { name: 'Enviar instrucciones' });
            await send.scrollIntoViewIfNeeded();
            assert.equal(await send.isVisible(), true);
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, width);
            await page.keyboard.press('Escape');
        }

        await page.goto(`${base}/password-reset/confirm`);
        await page.getByText('El enlace de recuperación es inválido', { exact: false }).waitFor();
        assert.equal(await page.getByRole('button', { name: 'Actualizar contraseña' }).isDisabled(), true);

        await page.goto(`${base}/password-reset/confirm?token=token-sintetico`);
        await page.waitForURL(`${base}/password-reset/confirm`);
        const newPassword = page.locator('#nueva_password');
        const confirm = page.locator('#confirm_password');
        const submit = page.getByRole('button', { name: 'Actualizar contraseña' });
        await newPassword.fill('Clave-Sintetica-123!');
        await confirm.fill('Clave-distinta');
        await submit.click();
        await page.getByRole('alert').filter({ hasText: 'Las contraseñas no coinciden.' }).waitFor();
        await confirm.fill('Clave-Sintetica-123!');
        assert.equal(await page.locator('#password-checklist .valid').count(), 5);
        await submit.click();
        await page.getByText('Contraseña actualizada con éxito.', { exact: false }).waitFor();
        await page.waitForURL(`${base}/`);
        assert.deepEqual(errors, []);
        console.log('Acceso y recuperación: visibilidad de contraseña, foco, envío y validación, token, redirección y diseño adaptable.');
    } finally {
        await browser.close();
    }
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});

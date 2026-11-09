// Integración en navegador con base local sintética; no ejecutar en producción.
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.FRONTEND_TEST_URL || 'https://127.0.0.1:8769';
const output = process.env.FRONTEND_SCREENSHOT_DIR;
const installerHash = process.env.PC_BROWSER_INSTALLER_SHA256;
const ok = data => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) });
(async () => {
    const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) });
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1100 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const checkInstaller = async container => {
        if (!installerHash) {
            await container.getByText('El instalador de Windows x64 no está disponible.', { exact: false }).waitFor();
            return;
        }
        const link = container.getByRole('link', { name: 'Descargar instalador para Windows x64' });
        const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
        assert.match(download.suggestedFilename(), /^PsycodeAgent-Setup-\d+\.\d+\.\d+-x64\.exe$/);
        assert.equal(createHash('sha256').update(fs.readFileSync(await download.path())).digest('hex'), installerHash);
    };
    const login = async (tab, username) => {
        await tab.goto(base);
        const status = await tab.evaluate(async username => {
            const csrf = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).slice(10);
            return (await fetch('/api/v1/auth/login', { method: 'POST', headers: {
                'Content-Type': 'application/json', 'X-Psycode-Browser': '1', 'X-CSRFToken': csrf
            }, body: JSON.stringify({ usuario: username, password: 'Synthetic-browser-2026!' }) })).status;
        }, username);
        assert.equal(status, 200);
    };
    try {
        await login(page, 'pcs-browser');
        await page.goto(`${base}/api/v1/pcs/panel`);
        await checkInstaller(page.locator('.pcs-descarga-inicial'));
        await page.getByRole('heading', { name: 'PC Box 3', exact: true }).waitFor();
        assert.equal((await page.locator('body').innerText()).includes('catálogo'), false);
        await page.getByRole('button', { name: 'Crear nuevo PC en Box 4', exact: true }).waitFor();
        // El sidebar usa exactamente los estilos compartidos con Configuración operativa.
        const sidebarStyle = await page.locator('.barra-lateral').evaluate(el => {
            const s = getComputedStyle(el); return [s.width, s.backgroundColor, s.padding, s.position];
        });
        const other = await context.newPage();
        await other.goto(`${base}/configuracion-operativa`);
        assert.deepEqual(await other.locator('.barra-lateral').evaluate(el => {
            const s = getComputedStyle(el); return [s.width, s.backgroundColor, s.padding, s.position];
        }), sidebarStyle);
        await other.close();
        // Catálogo real recibido por la API del colector; no se inventan IDs desde el nombre.
        await page.evaluate(async () => {
            const headers={'Content-Type':'application/json',Authorization:'Agent collector-test.'+'S'.repeat(43)};
            const issued=await (await fetch('/api/v1/internal/agenda-collections',{method:'POST',headers,body:JSON.stringify({source:'smile'})})).json();
            const response=await fetch('/api/v1/internal/smile-room-catalogues',{method:'POST',headers,body:JSON.stringify({version:'1.0',source:'smile',collection_id:issued.data.collection_id,rooms:[
                {box:'box-3',name:'BOX DE ATENCIÓN 3',smile_box_id:'77'},
                {box:'box-18',name:'BOX DE ATENCIÓN 18',smile_box_id:'91'}]})});
            if(response.status!==200)throw Error('catalogue rejected');
        });
        await page.locator('#actualizarPCs').click();
        const roomButton=page.getByRole('button',{name:'Crear nuevo PC en Box 18',exact:true});
        await roomButton.waitFor();
        if(output)await page.screenshot({path:`${output}/smile-salas.png`,fullPage:true});
        await roomButton.focus();await page.keyboard.press('Enter');
        assert.equal(await page.locator('#nombrePC').evaluate(x=>x===document.activeElement),true);
        await page.keyboard.press('Shift+Tab');
        assert.equal(await page.evaluate(()=>document.activeElement.closest('dialog')?.id),'dialogoPC');
        await page.keyboard.press('Escape');
        assert.equal(await roomButton.evaluate(x=>x===document.activeElement),true);
        await roomButton.click();
        assert.equal(await page.locator('#nuevoBoxPC').count(), 0);
        await page.locator('#nombrePC').fill('Box 18');
        await page.locator('#guardarPC').click();
        await page.locator('#dialogoCredencialPC[open]').waitFor();
        assert.equal(await page.locator('#servidorCredencialPC').textContent(), new URL(base).origin);
        const code = await page.locator('#secretoPC').inputValue();
        assert.match(code, /^[A-HJ-NP-Z2-9]{5}$/);
        await checkInstaller(page.locator('#dialogoCredencialPC'));
        assert.equal(await page.locator('#secretoPC').inputValue(), code);
        assert.equal(await page.locator('#identidadCredencialPC').count(), 0);
        const { spawnSync } = require('node:child_process');
        const privateRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pcs-pair-test-'));
        const envFile = path.join(privateRoot, 'agent.env');
        fs.writeFileSync(envFile, `OBSW_PASSWORD=synthetic-test\nSTREAM_URL=rtmp://localhost/test\nAGENT_STATE_ROOT=${privateRoot}/state\n`, { mode: 0o600 });
        const python = process.env.PC_PAIRING_AGENT_PYTHON;
        assert.ok(python, 'Configurar PC_PAIRING_AGENT_PYTHON con el agente instalado');
        const pairAndConnect = secret => {
            const script = `import os,sys
from psycode_agent.pairing import pair
from psycode_agent.config import AgentConfig
from psycode_agent.control import WebSocketControl
pair(server=sys.argv[1], code=sys.stdin.read().strip(), env_file=sys.argv[2])
os.environ['PSYCODE_ENV_FILE']=sys.argv[2]
c=WebSocketControl(AgentConfig.from_env())
try:
 c.open()
 c.status(pending=0,free_bytes=1024,remaining_seconds=10,capturing=False,operational_code='')
finally: c.close()
`;
            const result = spawnSync(python, ['-c', script, base, envFile], {
                input: secret, encoding: 'utf8', env: process.env, timeout: 30000
            });
            assert.equal(result.status, 0, 'El agente debe canjear el código y autenticarse por WSS sin copiar keys');
        };
        if (output) await page.screenshot({ path: `${output}/pcs-codigo.png` });
        pairAndConnect(code);
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#secretoPC').inputValue(), '');
        await page.locator('#actualizarPCs').click();
        await page.locator('.pc-tarjeta').first().waitFor();
        const listed = await page.evaluate(async () => (await fetch('/api/v1/pcs')).json());
        const createdPC = listed.data.find(pc => pc.name === 'Box 18');
        const id = createdPC.agent_id;
        assert.equal(createdPC.box, 'box-18');
        assert.equal(createdPC.credential_state, 'active');
        const saved = fs.readFileSync(envFile, 'utf8');
        const key = saved.match(/PSYCODE_AGENT_TOKEN='([^']+)'/)[1];
        assert.equal(JSON.stringify(listed).includes(key), false);
        assert.equal((await page.locator('body').innerText()).includes(key), false);
        assert.equal(await page.evaluate(key => [...Object.values(localStorage), ...Object.values(sessionStorage)].some(x => x.includes(key)), key), false);
        assert.match(saved, /OBSW_PASSWORD=synthetic-test/);
        const createdCard = page.locator('[data-agent-id]').filter({ has: page.getByRole('heading', { name: 'Box 18', exact: true }) });
        await createdCard.locator('summary').click();
        await page.getByRole('button', { name: 'Reinstalar o reemplazar Box 18', exact: true }).click();
        await page.locator('#confirmarAccionPC').click();
        await page.locator('#dialogoCredencialPC[open]').waitFor();
        const next = await page.locator('#secretoPC').inputValue();
        assert.notEqual(next, code);
        pairAndConnect(next);
        await page.locator('#cerrarCredencialPC').click();
        await page.getByRole('button', { name: 'Deshabilitar acceso de Box 18', exact: true }).click();
        await page.locator('#confirmarAccionPC').click();
        await page.locator('.pc-badge.revocado').waitFor();
        assert.equal(await page.getByRole('button', { name: 'Deshabilitar acceso de Box 18' }).isDisabled(), true);
        const current = await page.evaluate(async () => (await fetch('/api/v1/pcs')).json());
        assert.equal(current.data.find(pc => pc.name === 'Box 18').agent_id, id);
        fs.rmSync(privateRoot, { recursive: true, force: true });
        // Permisos con cookies reales: el supervisor no obtiene HTML ni puede operar las APIs.
        const supervisor = await browser.newContext({ ignoreHTTPSErrors: true });
        const supervisorPage = await supervisor.newPage();
        await login(supervisorPage, 'pcs-supervisor');
        const denied = await supervisorPage.goto(`${base}/api/v1/pcs/panel`);
        assert.equal(denied.status(), 403);
        assert.equal(await supervisorPage.locator('#crearPC').count(), 0);
        await supervisor.close();
        // Estados de carga/error/reintento y telemetría con respuestas sintéticas controladas.
        let mode = 'hold', release, roomsFailed = false;
        const pcs = [3, 4, 5, 6, 7].map((n, i) => ({ agent_id: `00000000-0000-4000-8000-00000000000${n}`, name: `PC Consulta · Box ${n}`, box: `box-${n}`, active: i !== 4,
            smile_room_id: `room-${n}`, room_available:true, version: '1.0.0', connection: i < 3 ? 'online' : 'offline', last_seen_at: '2026-11-08T16:40:00Z', capturing: i < 2,
            pending: i * 3, free_bytes: (i === 1 ? 2 : 44 + i) * 1024 ** 3, remaining_seconds: i === 1 ? 1500 : 90000,
            capture_status: i < 2 ? 'active' : 'finished', reception_status: 'pending', processing_status: 'complete',
            storage_warning: { active: i === 1, level: 'critical' }, last_audio: { accepted_at: '2026-11-08T16:39:32Z' } }));
        await page.route('**/api/v1/pcs/salas', route => route.fulfill(roomsFailed ? { status: 503, body: 'PRIVATE_ROOMS' } : ok(mode==='empty'?[]:pcs.map((pc,i)=>({room_id:pc.smile_room_id,box:pc.box,name:`BOX DE ATENCIÓN ${i+3}`,smile_box_id:String(77+i),pc_id:pc.agent_id,existing_pc_id:pc.agent_id,existing_pc_name:pc.name,available:true})))));
        await page.route('**/api/v1/pcs', async route => {
            if (mode === 'hold') await new Promise(resolve => { release = resolve; });
            await route.fulfill(mode === 'error' ? { status: 503, body: 'PRIVATE_TRACE' } : ok(mode === 'empty' ? [] : pcs));
        });
        await page.locator('#actualizarPCs').click();
        await page.locator('#estadoPCs[data-estado="carga"]').waitFor();
        assert.equal(await page.locator('#actualizarPCs').isDisabled(), true);
        mode = 'error'; release();
        await page.locator('#estadoPCs[data-estado="error"]').waitFor();
        assert.equal((await page.locator('body').innerText()).includes('PRIVATE_TRACE'), false);
        mode = 'data';
        await page.locator('#reintentarPCs').click();
        await page.waitForFunction(() => !document.getElementById('actualizarPCs').disabled);
        await page.locator('.pc-tarjeta').nth(4).waitFor();
        assert.equal(await page.locator('.pc-tarjeta').count(), 5);
        assert.equal(await page.locator('#crearPC').isEnabled(), true);
        await page.locator('#crearPC').click();
        await page.locator('#dialogoPC[open]').waitFor();
        assert.match(await page.locator('#salaFormularioPC').innerText(), /Todos los boxes/);
        assert.equal(await page.locator('#guardarPC').isDisabled(), true);
        await page.keyboard.press('Escape');
        roomsFailed = true;
        pcs[0].pending = 17;
        await page.locator('#actualizarPCs').click();
        await page.locator('#avisoSalasPCs:not([hidden])').waitFor();
        await page.waitForFunction(() => !document.getElementById('actualizarPCs').disabled);
        assert.equal(await page.locator('.pc-tarjeta').count(), 5);
        assert.match(await page.locator('[data-agent-id]').first().innerText(), /17/);
        assert.equal((await page.locator('body').innerText()).includes('PRIVATE_ROOMS'), false);
        roomsFailed = false;
        await page.locator('#actualizarPCs').click();
        await page.waitForFunction(() => !document.getElementById('actualizarPCs').disabled);
        await page.locator('#boxPC').selectOption('box-7');
        assert.equal(await page.locator('.pc-tarjeta').count(), 1);
        await page.locator('#boxPC').selectOption('');
        await page.locator('#buscarPC').fill('no existe');
        await page.getByText('No hay salas o equipos que coincidan con los filtros.').waitFor();
        await page.locator('#buscarPC').fill('');
        if (output) await page.screenshot({ path: `${output}/pcs-desktop.png`, fullPage: true });
        // Los nombres son texto; nunca se interpretan como HTML ejecutable.
        pcs[0].name = '<img src=x onerror="window.pcXss=true">';
        await page.locator('#actualizarPCs').click();
        await page.getByRole('heading', { name: pcs[0].name, exact: true }).waitFor();
        assert.equal(await page.locator('.pc-nombre img').count(), 0);
        assert.equal(await page.evaluate(() => Boolean(window.pcXss)), false);
        pcs[0].name = 'PC Consulta · Box 3';
        await page.locator('#actualizarPCs').click();
        await page.getByRole('heading', { name: pcs[0].name, exact: true }).waitFor();
        // Historial: página 2, filtros y recuperación estimada/desconocida, sin confundir procedencia.
        let historyMode = 'data', historyRequests = [];
        await page.route('**/historial?*', async route => {
            const params = new URL(route.request().url()).searchParams;
            historyRequests.push(params.toString());
            const row = { box: 'box-3', channel: 'wss', source: 'server_inferred', active: false,
                started_at: '2026-11-08T15:00:00Z', recovered_at: '2026-11-08T15:05:00Z', duration_ms: 300000, cause: 'UNKNOWN',
                start_time_quality: 'estimated', recovery_time_quality: 'estimated', received_at: '2026-11-08T15:01:00Z' };
            await route.fulfill(historyMode === 'error' ? { status: 503, body: 'PRIVATE_HISTORY' } : ok({
                results: historyMode === 'empty' ? [] : [row, { ...row, source: 'agent_reported', started_at: null, duration_ms: null, start_time_quality: 'unknown' }],
                pagination: { page: Number(params.get('page')), page_size: 10, total: historyMode === 'empty' ? 0 : 12, total_pages: historyMode === 'empty' ? 0 : 2 }
            }));
        });
        const historyButton = page.getByRole('button', { name: 'Ver historial de PC Consulta · Box 3', exact: true });
        await historyButton.click();
        await page.getByText('Inferido por el servidor', { exact: true }).waitFor();
        assert.match(await page.locator('#listaHistorialPC').innerText(), /Tiempo estimado/);
        assert.match(await page.locator('#listaHistorialPC').innerText(), /Tiempo desconocido/);
        await page.locator('#siguienteHistorialPC').click();
        await page.getByText('Página 2 de 2', { exact: false }).waitFor();
        assert.equal(await page.locator('#siguienteHistorialPC').isDisabled(), true);
        await page.locator('#desdeHistorialPC').fill('2026-11-01');
        await page.locator('#hastaHistorialPC').fill('2026-11-08');
        await page.getByRole('button', { name: 'Aplicar filtros' }).click();
        await page.getByText('Página 1 de 2', { exact: false }).waitFor();
        assert.match(historyRequests.at(-1), /desde=2026-11-01/);
        await page.locator('#hastaHistorialPC').fill('2026-10-01');
        const before = historyRequests.length;
        await page.getByRole('button', { name: 'Aplicar filtros' }).click();
        assert.equal(await page.locator('#hastaHistorialPC').evaluate(x => x.validity.valid), false);
        assert.equal(historyRequests.length, before);
        await page.locator('#hastaHistorialPC').fill('2026-11-08');
        historyMode = 'error'; await page.getByRole('button', { name: 'Aplicar filtros' }).click();
        await page.locator('#estadoHistorialPC[data-estado="error"]').waitFor();
        assert.equal((await page.locator('#dialogoHistorialPC').innerText()).includes('PRIVATE_HISTORY'), false);
        historyMode = 'empty'; await page.locator('#reintentarHistorialPC').click();
        await page.locator('#estadoHistorialPC[data-estado="vacio"]').waitFor();
        historyMode = 'data'; await page.locator('#limpiarHistorialPC').click();
        await page.locator('.pcs-incidente').first().waitFor();
        if (output) await page.screenshot({ path: `${output}/pcs-historial.png`, fullPage: true });
        // Escape y restitución del foco en el botón de origen.
        await page.keyboard.press('Escape');
        assert.equal(await historyButton.evaluate(x => x === document.activeElement), true);
        for (const width of [375, 768, 1024, 1440]) {
            await page.setViewportSize({ width, height: 1000 });
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Sin desbordamiento a ${width}px`);
            if (output && width === 375) await page.screenshot({ path: `${output}/pcs-mobile.png`, fullPage: true });
        }
        await historyButton.focus();
        pcs[0].pending = 23;
        await page.waitForTimeout(16500);
        assert.equal(await historyButton.evaluate(x => x === document.activeElement), true);
        assert.match(await page.locator('[data-agent-id]').first().innerText(), /23/);
        await historyButton.focus(); await page.keyboard.press('Enter');
        await page.locator('#dialogoHistorialPC[open]').waitFor(); await page.keyboard.press('Escape');
        mode = 'empty'; await page.locator('#actualizarPCs').click();
        await page.locator('#estadoPCs[data-estado="vacio"]').waitFor();
        assert.deepEqual(errors, []);
        console.log('PCs: registro sin catálogo, disponibilidad independiente, instalación recuperable HTTPS + WSS, revocación, permisos, filtros, actualización automática con foco preservado, teclado y 4 tamaños OK.');
    } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });

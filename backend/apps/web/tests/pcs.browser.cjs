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
    const scrum97 = process.env.SCRUM97_ONLY === '1';
    if (scrum97) assert.equal(new URL(base).hostname, '127.0.0.1');
    const launch = { headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
        ...(scrum97 ? {proxy:{server:'http://127.0.0.1:9',bypass:'127.0.0.1,localhost'},
            args:['--disable-background-networking','--disable-crash-reporter',`--crash-dumps-dir=${output}`]} : {}) };
    const browser = scrum97 ? null : await chromium.launch(launch);
    const context = scrum97 ? await chromium.launchPersistentContext(path.join(output,'browser-profile'),
        {...launch,ignoreHTTPSErrors:true,viewport:{width:1440,height:1100}})
        : await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1100 } });
    if (scrum97) await context.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin
        ? route.continue() : route.abort('blockedbyclient'));
    const page = await context.newPage();
    await page.clock.install();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const configurationRequests=[];
    if(scrum97) page.on('request',request=>{
        if(/\/api\/v1\/internal\/pcs\/[^/]+\/config(?:\?|$)/.test(request.url())) configurationRequests.push(request.method());
    });
    const checkInstaller = async container => {
        if (!installerHash) {
            await container.getByText('El instalador de Windows x64 no está disponible.', { exact: false }).waitFor();
            return;
        }
        const link = container.getByRole('link', { name: 'Descargar instalador para Windows x64' });
        const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
        assert.match(download.suggestedFilename(), /^PsycodeAgent-Setup-\d+\.\d+\.\d+-x64\.exe$/);
        assert.equal(createHash('sha256').update(fs.readFileSync(await download.path())).digest('hex'), installerHash);
        const [checksum] = await Promise.all([
            page.waitForEvent('download'), container.getByRole('link', { name: 'Descargar SHA-256' }).click()
        ]);
        assert.equal(checksum.suggestedFilename(), download.suggestedFilename() + '.sha256');
        assert.equal(fs.readFileSync(await checksum.path(), 'utf8').trim(), `${installerHash}  ${download.suggestedFilename()}`);
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
        if (scrum97) {
            const card=page.locator('.pc-tarjeta[data-box="box-3"]');
            await card.getByRole('heading',{name:'PC Box 3',exact:true}).waitFor();
            const agentId=await card.getAttribute('data-agent-id');
            const assertNoManualConfiguration=async()=>{
                assert.equal(await page.getByRole('button',{name:'Configurar agente',exact:true}).count(),0);
                assert.equal(await page.getByRole('dialog',{name:/Configuración de/}).count(),0);
                assert.equal(await page.getByLabel('Intervalo de comunicación (segundos)').count(),0);
                assert.equal(await page.getByRole('button',{name:'Recuperar última válida',exact:true}).count(),0);
                for(const label of ['Versión deseada','Versión efectiva','Revisión local efectiva'])
                    assert.equal(await page.getByText(label,{exact:true}).count(),0);
            };
            await assertNoManualConfiguration();
            const rename=card.getByRole('button',{name:'Cambiar nombre de PC Box 3'});
            await rename.click();
            const renameDialog=page.getByRole('dialog',{name:'Cambiar nombre del PC',exact:true});
            await renameDialog.getByRole('textbox',{name:'Nombre del PC'}).waitFor();
            await page.keyboard.press('Escape');
            await renameDialog.waitFor({state:'hidden'});
            assert.equal(await rename.evaluate(el=>el===document.activeElement),true);
            assert.equal(await card.getByRole('button',{name:'Ver historial de PC Box 3'}).isVisible(),true);
            await page.setViewportSize({width:375,height:812});
            await page.reload();
            await card.getByRole('heading',{name:'PC Box 3',exact:true}).waitFor();
            await assertNoManualConfiguration();
            assert.deepEqual(configurationRequests,[],'Gestión de PCs no consulta ni modifica configuración técnica');
            const observed=JSON.parse(fs.readFileSync(path.join(output,'observed.json')));
            assert.equal(observed.ready,true);
            assert.equal(observed.heartbeat,15);
            assert.equal(observed.duration,60);
            assert.equal(observed.ack_pending,false);
            await page.goto(`${base}/configuracion-operativa`);
            await page.getByRole('link',{name:'Captura de audio',exact:true}).click();
            const globalDuration=page.getByLabel('Duración del fragmento (segundos)',{exact:true});
            await globalDuration.waitFor();
            await page.locator('input[type=radio][value=session]').check();
            assert.equal(await globalDuration.isDisabled(),true);
            await page.locator('input[type=radio][value=fixed]').check();
            assert.equal(await globalDuration.isEnabled(),true);
            await context.clearCookies();
            await login(page,'pcs-supervisor');
            assert.equal((await page.goto(`${base}/api/v1/pcs/panel`)).status(),403);
            assert.equal(await page.evaluate(async url=>(await fetch(url)).status,
                `/api/v1/internal/pcs/${agentId}/config`),403);
            assert.deepEqual(errors,[]);
            console.log('SCRUM97_UI_NO_MANUAL_CONFIG_OK: no button/modal/heartbeat/version/recovery controls, no config API requests on PC page, desktop/mobile/reload, rename/focus/history preserved, automatic WSS heartbeat15, global fixed/session controls, supervisor403; no screenshots.');
            return;
        }
        await checkInstaller(page.locator('.pcs-descarga-inicial'));
        await page.getByRole('heading', { name: 'PC Box 3', exact: true }).waitFor();
        assert.equal((await page.locator('body').innerText()).includes('catálogo'), false);
        const freeBox = page.locator('.pc-tarjeta[data-box="box-4"]');
        const createInBox = freeBox.getByRole('button', { name: 'Crear nuevo PC en Box 4', exact: true });
        await createInBox.waitFor();
        const installedBox = page.locator('.pc-tarjeta[data-box="box-3"]');
        const [installedBounds, freeBounds] = await Promise.all([installedBox.boundingBox(), freeBox.boundingBox()]);
        assert.equal(installedBounds.y, freeBounds.y);
        assert.ok(freeBounds.height < installedBounds.height, 'La tarjeta vacía conserva su altura natural');

        const search = page.getByRole('searchbox', { name: 'Buscar sala o equipo' });
        await search.fill('PC Box 3');
        await page.setViewportSize({ width: 375, height: 812 });
        const rename = installedBox.getByRole('button', { name: 'Cambiar nombre de PC Box 3' });
        const renameDialog = page.getByRole('dialog', { name: 'Cambiar nombre del PC' });
        const nameInput = renameDialog.getByRole('textbox', { name: 'Nombre del PC' });
        await rename.focus();
        await page.keyboard.press('Enter');
        assert.equal(await nameInput.inputValue(), 'PC Box 3');
        assert.equal(await nameInput.evaluate(el => el === document.activeElement), true);
        await nameInput.fill('   ');
        await renameDialog.getByRole('button', { name: 'Guardar nombre' }).click();
        await renameDialog.getByRole('alert').getByText('Escribe un nombre para el PC.').waitFor();
        await page.keyboard.press('Escape');
        assert.equal(await rename.evaluate(el => el === document.activeElement), true);
        await rename.click();
        assert.equal(await nameInput.inputValue(), 'PC Box 3');
        const installedId = await installedBox.getAttribute('data-agent-id');
        await nameInput.fill('  PC Recepción  ');
        await nameInput.press('Enter');
        await page.getByRole('status').getByText('Nombre del PC guardado.').waitFor();
        assert.equal(await search.evaluate(el => el === document.activeElement), true);
        await search.fill('PC Recepción');
        await installedBox.getByRole('heading', { name: 'PC Recepción' }).waitFor();
        assert.equal(await installedBox.getAttribute('data-agent-id'), installedId);
        await page.reload();
        await installedBox.getByRole('heading', { name: 'PC Recepción' }).waitFor();
        await page.setViewportSize({ width: 1440, height: 1100 });

        await createInBox.click();
        await page.locator('#guardarPC').click();
        await page.locator('#dialogoCredencialPC[open]').waitFor();
        await page.locator('#cerrarCredencialPC').click();
        await freeBox.getByText('Pendiente de instalación').waitFor();
        assert.equal(await freeBox.locator('.pc-datos, .pc-flujo-bloque, summary').count(), 0);
        assert.equal(await freeBox.getByRole('button', { name: /Ver historial/ }).count(), 0);
        await freeBox.getByRole('button', { name: 'Cambiar nombre de Box 4', exact: true }).click();
        await nameInput.fill('PC pendiente');
        await nameInput.press('Enter');
        await freeBox.getByRole('heading', { name: 'PC pendiente' }).waitFor();
        if (output) await page.screenshot({ path: `${output}/pcs-tarjetas-mixtas.png` });
        await freeBox.getByRole('button', { name: 'Cancelar instalación de PC pendiente' }).click();
        await page.locator('#confirmarAccionPC').click();
        await createInBox.waitFor();
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
            smile_room_id: `room-${n}`, room_available:true, version: '1.0.0', connection: n === 3 || n === 5 ? 'online' : 'offline',
            last_seen_at: n === 7 ? null : `2026-11-08T16:4${n}:00Z`, capturing: i < 2,
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
        const ordenBoxes = () => page.locator('.pc-tarjeta').evaluateAll(cards => cards.map(card => card.dataset.box));
        assert.deepEqual(await ordenBoxes(), ['box-3', 'box-5', 'box-6', 'box-4', 'box-7']);
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
        // Diagnóstico de Smile: el botón queda bloqueado mientras hay una solicitud en curso.
        pcs[0].smile_sources = ['smile'];
        pcs[0].smile_check_supported = true;
        await page.route(`**/api/v1/pcs/${pcs[0].agent_id}/smile/prueba`, async route => {
            assert.deepEqual(route.request().postDataJSON(), { source: 'smile' });
            await route.fulfill(ok({ source: 'smile', state: 'queued' }));
        });
        await page.locator('#actualizarPCs').click();
        const smileButton = page.getByRole('button', { name: 'Probar colector', exact: true });
        await smileButton.click();
        await page.getByText('Esperando al colector…', { exact: true }).waitFor();
        assert.equal(await smileButton.isDisabled(), true);
        pcs[0].smile_check = { source: 'smile', state: 'finished', result: 'ok' };
        await page.locator('#actualizarPCs').click();
        await page.getByText('Acceso a Smile y selector de salas verificados.', { exact: true }).waitFor();
        assert.equal(await smileButton.isEnabled(), true);
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
        for (const viewport of [{ width: 320, height: 568 }, { width: 667, height: 375 }]) {
            await page.setViewportSize(viewport);
            const dialog = page.locator('#dialogoHistorialPC');
            assert.equal(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth), true,
                `Historial sin desbordamiento a ${viewport.width}×${viewport.height}`);
            const next = page.locator('#siguienteHistorialPC');
            await next.scrollIntoViewIfNeeded();
            const bounds = await next.boundingBox();
            assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= viewport.width &&
                bounds.y >= 0 && bounds.y + bounds.height <= viewport.height,
                'Paginación accesible al desplazar el diálogo');
        }
        await page.setViewportSize({ width: 1440, height: 1100 });
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
        pcs[2].connection = 'offline';
        pcs[3].connection = 'online';
        const refresh = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/pcs' &&
            response.request().method() === 'GET' && response.ok());
        await page.clock.fastForward(16500);
        await refresh;
        const pending = page.locator('.pc-tarjeta[data-box="box-3"]')
            .getByText('Pendientes del PC', { exact: true }).locator('..').locator('dd');
        await pending.filter({ hasText: /^23$/ }).waitFor();
        assert.equal(await historyButton.evaluate(x => x === document.activeElement), true);
        assert.deepEqual(await ordenBoxes(), ['box-3', 'box-6', 'box-5', 'box-4', 'box-7']);
        await historyButton.focus(); await page.keyboard.press('Enter');
        await page.locator('#dialogoHistorialPC[open]').waitFor(); await page.keyboard.press('Escape');
        mode = 'empty'; await page.locator('#actualizarPCs').click();
        await page.locator('#estadoPCs[data-estado="vacio"]').waitFor();
        assert.deepEqual(errors, []);
        console.log('PCs: registro, salas, instalación HTTPS + WSS, revocación, permisos, Smile, filtros, foco, teclado y tamaños móviles y de escritorio OK.');
    } finally { if(browser) await browser.close(); else await context.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });

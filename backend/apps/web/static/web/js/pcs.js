/* Registro de PCs: usa las cookies y el transporte común, sin persistir secretos. */
(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const endpoint = '/api/v1/pcs';
    const fmt = new Intl.DateTimeFormat('es-CL', { timeZone: 'America/Santiago', dateStyle: 'short', timeStyle: 'medium' });
    let equipos = [], salas = [], cargando = false, mutando = false, objetivo = null;
    let historialPC = null, pagina = 1, totalPaginas = 0, filtros = {}, consultaHistorial = null;
    const origenes = new Map();
    let ultimaConsulta = null, temporizador = null, consultaPCs = null, consultaSalas = null, salasConsultadas = false;
    const nodos = (tag, texto, clase) => {
        const el = document.createElement(tag);
        if (texto != null) el.textContent = texto;
        if (clase) el.className = clase;
        return el;
    };
    const fecha = value => {
        if (!value) return 'Sin datos';
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? 'Desconocida' : fmt.format(d);
    };
    const boxNombre = value => /^box-[1-9][0-9]{0,11}$/.test(value) ? `Box ${value.slice(4)}` : 'Box desconocido';
    const numero = value => Number.isFinite(value) && value >= 0;
    const informado = (pc, campo) => !Array.isArray(pc.telemetry_fields) || pc.telemetry_fields.includes(campo);
    const duracion = seconds => {
        if (!numero(seconds)) return 'Desconocida';
        if (seconds < 60) return `${Math.floor(seconds)} s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
        return `${Math.floor(seconds / 3600)} h ${Math.floor(seconds % 3600 / 60)} min`;
    };
    const espacio = bytes => {
        if (!numero(bytes)) return 'Sin datos';
        const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
        const index = bytes ? Math.min(4, Math.floor(Math.log(bytes) / Math.log(1024))) : 0;
        return `${new Intl.NumberFormat('es-CL', { maximumFractionDigits: 1 }).format(bytes / 1024 ** index)} ${units[index]}`;
    };
    const estados = { no_session: 'Sin sesión', active: 'En curso', started: 'Iniciando', pending: 'Pendiente',
        completed: 'Completado', closed: 'Cerrado', failed: 'Fallido', stopped: 'Detenido',
        stopping: 'Deteniendo', interrupted: 'Interrumpido', receiving: 'Recibiendo', processing: 'Procesando',
        waiting: 'En espera', idle: 'En espera', complete: 'Completo', draining: 'Recibiendo pendientes',
        queued: 'En cola', review: 'Requiere revisión', partial: 'Parcial', delayed: 'Con retraso',
        finished: 'Finalizada', stop_unconfirmed: 'Detención sin confirmar', start_unconfirmed: 'Inicio sin confirmar',
        intervention_required: 'Requiere intervención' };
    const estado = value => estados[value] || 'Sin información';
    const causas = { UNKNOWN: 'Causa desconocida', TIMEOUT: 'Tiempo de espera agotado', CONNECTION_ERROR: 'Error de conexión',
        CONNECTION_LOST: 'Conexión perdida', CONNECTION_TIMEOUT: 'Sin mensajes del PC', HTTP_ERROR: 'Error HTTPS',
        DISK_LOW: 'Disco con poco espacio', STORAGE_WARNING: 'Capacidad baja', STORAGE_CRITICAL: 'Capacidad crítica',
        LOCAL_WRITE_FAILED: 'Error al escribir en disco', RECOVERY_REQUIRED: 'Recuperación requerida',
        CREDENTIAL_REVOKED: 'Credencial revocada', CREDENTIAL_RENEWED: 'Credencial renovada', CREDENTIAL_INVALIDATED: 'Credencial invalidada' };

    function abrir(id, foco) {
        const dialogo = $(id);
        origenes.set(id, document.activeElement);
        dialogo.showModal();
        (foco || dialogo.querySelector('[autofocus], input, button'))?.focus();
    }
    document.querySelectorAll('[data-cerrar]').forEach(b => b.addEventListener('click', () => {
        if (!mutando) $(b.dataset.cerrar).close();
    }));
    document.querySelectorAll('dialog').forEach(d => {
        d.addEventListener('cancel', e => {
            if (mutando) e.preventDefault();
        });
        d.addEventListener('close', () => {
            const origen = origenes.get(d.id);
            (origen?.isConnected ? origen : $('crearPC')).focus();
            origenes.delete(d.id);
        });
    });
    function mensaje(id, texto, tipo = '') {
        const el = $(id);
        el.textContent = texto;
        el.dataset.estado = tipo;
        el.hidden = !texto;
    }
    function dato(dl, titulo, valor) {
        const group = nodos('div');
        group.append(nodos('dt', titulo), nodos('dd', valor));
        dl.append(group);
        return group.lastChild;
    }
    function boton(texto, accion, clase = '') {
        const b = nodos('button', texto, `pcs-boton ${clase}`);
        b.type = 'button';
        b.addEventListener('click', accion);
        return b;
    }
    function tarjeta(pc) {
        const article = nodos('article', null, 'pc-tarjeta');
        article.dataset.agentId = pc.agent_id;
        const header = nodos('header', null, 'pc-tarjeta-cabecera');
        const identity = nodos('div', null, 'pc-identidad');
        identity.append(nodos('span', boxNombre(pc.box).toUpperCase(), 'pc-box'), nodos('h3', pc.name, 'pc-nombre'));
        const badges = nodos('div', null, 'pc-badges');

        const pendiente = pc.credential_state === 'pending_pairing';
        const vencido = pc.credential_state === 'pairing_expired';
        const instalacion = pendiente || vencido;
        badges.append(nodos('span', instalacion ? 'Pendiente de instalación' : !pc.active ? 'Acceso deshabilitado' : pc.connection === 'online' ? 'Conectado' : 'Sin comunicación', `pc-badge ${!pc.active && !instalacion ? 'revocado' : pc.connection === 'online' ? 'online' : ''}`));
        header.append(identity, badges);
        const details = nodos('dl', null, 'pc-datos');
        dato(details, 'Versión del agente', pc.version || 'Sin datos');
        dato(details, 'Última comunicación · Chile', fecha(pc.last_seen_at));
        dato(details, pc.connection === 'online' ? 'Captura informada por el PC' : 'Última captura informada', !informado(pc, 'capturing') ? 'Sin datos' : pc.capturing === true ? 'Capturando' : pc.capturing === false ? 'Sin captura' : 'Sin datos');

        const flow = nodos('section', null, 'pc-flujo-bloque');
        flow.append(nodos('h4', `Flujo de ${boxNombre(pc.box)}`));
        const steps = nodos('dl', null, 'pc-flujo');
        dato(steps, 'Captura', estado(pc.capture_status));
        dato(steps, 'Recepción', estado(pc.reception_status));
        dato(steps, 'Procesamiento', estado(pc.processing_status));
        flow.append(steps);
        const capacity = nodos('dl', null, 'pc-datos pc-capacidad');
        dato(capacity, 'Pendientes del PC', informado(pc, 'pending') && numero(pc.pending) ? String(pc.pending) : 'Sin datos');
        dato(capacity, 'Disco libre', espacio(pc.free_bytes));
        dato(capacity, 'Autonomía estimada', duracion(pc.remaining_seconds));
        article.append(header, details, nodos('p', `Último audio recibido de este PC · ${fecha(pc.last_audio?.accepted_at)}`, 'pc-ultimo-audio'), flow, capacity);
        if (pc.connection !== 'online' && pc.active) article.append(nodos('p', `Última comunicación: ${fecha(pc.last_seen_at)}. Comprueba que el PC esté encendido y tenga Internet. La aplicación intentará reconectarse automáticamente; conserva su instalación.`, 'pc-nota'));
        if (instalacion) article.append(nodos('p', vencido ? 'La instalación no se completó a tiempo. El técnico puede preparar otro código para este mismo PC.' : 'El técnico debe completar la instalación en el computador de este box.', 'pc-nota'));
        if (pc.room_available === false) article.append(nodos('p', 'La sala está deshabilitada. Solicita una revisión técnica antes de utilizarla.', 'pcs-aviso pc-aviso'));
        if (pc.connection === 'online' && pc.obs === 'unavailable') article.append(nodos('p', 'La aplicación de captura no responde. Comprueba que OBS esté abierto en la cuenta de Windows configurada. Si continúa, solicita asistencia técnica.', 'pcs-aviso pc-aviso'));
        if (pc.storage_warning?.active) article.append(nodos('p', pc.storage_warning.level === 'critical' ? 'Atención: capacidad crítica. Revisa el disco y los envíos pendientes.' : 'Aviso: capacidad baja. Revisa el espacio y la autonomía disponible.', `pcs-aviso pc-aviso ${pc.storage_warning.level === 'critical' ? 'critical' : ''}`));
        const ayuda = { RECOVERY_REQUIRED: 'Hay una captura pendiente de recuperación. Solicita asistencia técnica; los archivos se conservan.', UPLOAD_INTERVENTION: 'Hay envíos que necesitan revisión técnica. Los audios pendientes se conservan.', SMILE_UNAVAILABLE: 'La agenda no se ha podido actualizar. La aplicación volverá a intentarlo automáticamente.' };
        if (pc.operational_code && !pc.storage_warning?.active) article.append(nodos('p', ayuda[pc.operational_code] || 'El equipo informó un problema. Consulta el historial y solicita asistencia técnica si continúa.', 'pcs-aviso pc-aviso'));
        const footer = nodos('footer', null, 'pc-tarjeta-pie');
        const history = boton('Ver historial', () => abrirHistorial(pc));
        history.setAttribute('aria-label', `Ver historial de ${pc.name}`);
        const actions = nodos('details', null, 'pc-mantenimiento');
        actions.append(nodos('summary', 'Instalación y acceso'));
        const renovarTexto = instalacion ? 'Generar otro código' : 'Reinstalar o reemplazar';
        const renew = boton(renovarTexto, () => confirmar(pc, 'renovar'));
        renew.setAttribute('aria-label', instalacion ? `${renovarTexto} para ${pc.name}` : `${renovarTexto} ${pc.name}`);
        renew.disabled = pc.room_available === false;
        const revoke = boton('Deshabilitar acceso', () => confirmar(pc, 'revocar'), 'pcs-peligro');
        revoke.setAttribute('aria-label', `Deshabilitar acceso de ${pc.name}`);
        revoke.disabled = !pc.active && !pc.installation_pending;
        actions.append(renew, revoke);
        if (pc.installation_pending) actions.append(boton('Cancelar instalación pendiente', () => confirmar(pc, 'cancelar-instalacion')));
        footer.append(history, actions);
        article.append(footer);
        return article;
    }
    function abrirVinculacion(sala) {
        $('formularioPC').reset();
        const disponibles = salas.filter(item => item.available && !item.conflict && !equipos.some(pc => pc.box === item.box));
        $('salaPC').replaceChildren(...disponibles.map(item => new Option(boxNombre(item.box), item.box)));
        if (sala) $('salaPC').value = sala.box;
        $('nombrePC').value = sala ? boxNombre(sala.box) : '';
        const disponiblesActuales = disponibles.length > 0;
        $('salaFormularioPC').textContent = disponiblesActuales
            ? 'La configuración del agente se completa en el computador con un código temporal.'
            : !salasConsultadas
                ? 'No se pudo consultar qué boxes están disponibles. Cierra este formulario y pulsa Actualizar para volver a intentarlo.'
                : 'Todos los boxes disponibles ya tienen un PC o requieren revisión. Para reemplazar uno, utiliza «Instalación y acceso» en su tarjeta; así conserva su identidad e historial.';
        $('guardarPC').disabled = !disponiblesActuales;
        mensaje('errorFormularioPC', ''); abrir('dialogoPC', $('nombrePC'));
    }
    function tarjetaSala(sala) {
        const card = nodos('article', null, 'pc-tarjeta pc-sala');
        card.append(nodos('span', boxNombre(sala.box).toUpperCase(), 'pc-box'), nodos('h3', sala.name, 'pc-nombre'),
            nodos('span', sala.conflict ? 'Requiere revisión técnica' : !sala.available ? 'Sala deshabilitada' : 'Sin PC registrado', 'pc-badge'));
        card.append(nodos('p', sala.conflict ? 'Se encontraron varios equipos asociados a este box. Solicita una revisión técnica.' : 'Registra el computador que se utilizará en este box. El técnico completará su instalación.', 'pcs-ayuda'));
        const link = boton('Crear nuevo PC', () => abrirVinculacion(sala), 'pcs-primario');
        link.setAttribute('aria-label', `Crear nuevo PC en ${boxNombre(sala.box)}`);
        link.disabled = !sala.available || sala.conflict;
        card.append(link);
        return card;
    }
    function renderizar() {
        const activo = document.activeElement;
        const tarjetaActiva = activo?.closest('[data-agent-id]');
        const mantenerFoco = tarjetaActiva && $('listaPCs').contains(activo)
            ? { id: tarjetaActiva.dataset.agentId, tag: activo.tagName, label: activo.getAttribute('aria-label') || activo.textContent } : null;
        const abiertos = new Set([...$('listaPCs').querySelectorAll('[data-agent-id] details[open]')].map(el => el.closest('[data-agent-id]').dataset.agentId));
        const query = $('buscarPC').value.trim().toLocaleLowerCase('es');
        const box = $('boxPC').value;
        const matches = (b, text) => (!box || b === box) && text.toLocaleLowerCase('es').includes(query);
        const visibles = equipos.filter(pc => matches(pc.box, `${pc.name} ${pc.agent_id} ${boxNombre(pc.box)}`));
        const libres = salas.filter(sala => !equipos.some(pc => pc.box === sala.box) && matches(sala.box, `${sala.name} ${boxNombre(sala.box)}`));
        const cards = [...visibles.map(tarjeta), ...libres.map(tarjetaSala)];
        $('listaPCs').replaceChildren(...cards);
        for (const card of cards) if (abiertos.has(card.dataset.agentId)) card.querySelector('details')?.setAttribute('open', '');
        if (mantenerFoco) {
            const card = cards.find(item => item.dataset.agentId === mantenerFoco.id);
            const destino = card && [...card.querySelectorAll('button, summary')].find(el => el.tagName === mantenerFoco.tag && (el.getAttribute('aria-label') || el.textContent) === mantenerFoco.label);
            (destino || $('contenidoPCs')).focus({ preventScroll: true });
        }
        for (const id of ['boxPC', 'boxHistorialPC']) {
                const select = $(id), actual = select.value;
                const boxes = [...new Set([...equipos.map(pc => pc.box), ...salas.map(sala => sala.box)])].sort((a, b) => Number(a.slice(4)) - Number(b.slice(4)));
                select.replaceChildren(new Option('Todos los boxes', ''), ...boxes.map(box => new Option(boxNombre(box), box)));
                if (boxes.includes(actual)) select.value = actual;
            }
        $('cantidadPCs').textContent = `${visibles.length} de ${equipos.length} PCs registrados`;
        $('crearPC').disabled = false;
        mensaje('estadoPCs', !cards.length ? equipos.length || salas.length ? 'No hay salas o equipos que coincidan con los filtros.' : 'Todavía no hay equipos ni boxes configurados. La instalación inicial debe completarla el técnico.' : '', 'vacio');
    }
    async function cargarPCs({ automatica = false } = {}) {
        if (cargando || mutando) return;
        cargando = true;
        $('actualizarPCs').disabled = true;
        $('listaPCs').setAttribute('aria-busy', 'true');
        $('reintentarPCs').hidden = true;
        if (!automatica || !ultimaConsulta) mensaje('estadoPCs', equipos.length ? 'Actualizando equipos…' : 'Cargando equipos…', 'carga');
        consultaPCs = new AbortController(); consultaSalas = new AbortController();
        const limitePCs = setTimeout(() => consultaPCs?.abort(), 10000);
        const limiteSalas = setTimeout(() => consultaSalas?.abort(), 10000);
        // Una integración indisponible no bloquea la actualización del registro de PCs.
        const salasPendientes = apiGetDatos(`${endpoint}/salas`, { cache: 'no-store', signal: consultaSalas.signal })
            .then(rooms => {
                if (!Array.isArray(rooms) || rooms.some(room => !room || !(room.room_id == null || typeof room.room_id === 'string') || typeof room.name !== 'string' || typeof room.box !== 'string')) throw new Error('shape');
                salas = rooms; salasConsultadas = true; mensaje('avisoSalasPCs', '');
            }).catch(() => mensaje('avisoSalasPCs', 'No se pudo actualizar la disponibilidad de boxes. Los equipos se consultan por separado; volveremos a intentarlo automáticamente.'))
            .finally(() => clearTimeout(limiteSalas));
        try {
            const data = await apiGetDatos(endpoint, { cache: 'no-store', signal: consultaPCs.signal });
            if (!Array.isArray(data) || data.some(pc => !pc || typeof pc.name !== 'string' || typeof pc.agent_id !== 'string')) throw new Error('shape');
            equipos = data;
            mensaje('estadoPCs', '');
            ultimaConsulta = new Date().toISOString();
            $('actualizacionPCs').textContent = `Última consulta: ${fecha(ultimaConsulta)} · Actualización automática`;
            renderizar();
        } catch (error) {
            mensaje('estadoPCs', error.estado === 403 ? 'Solo un administrador puede consultar esta pantalla.' : 'No se pudo actualizar el estado. Se conserva la última información disponible y volveremos a intentarlo automáticamente.', 'error');
            $('reintentarPCs').hidden = error.estado === 403;
            $('actualizacionPCs').textContent = ultimaConsulta ? `Información sin actualizar desde ${fecha(ultimaConsulta)} · Chile` : 'Sin datos disponibles';
        } finally {
            clearTimeout(limitePCs);
            $('listaPCs').setAttribute('aria-busy', 'false');
            await salasPendientes;
            // Mantener el error del registro si su consulta falló.
            if ($('estadoPCs').dataset.estado !== 'error') renderizar();
            cargando = false;
            $('actualizarPCs').disabled = false;
            consultaPCs = consultaSalas = null;
        }
    }
    function actualizarAutomaticamente() {
        clearTimeout(temporizador);
        temporizador = setTimeout(async () => {
            if (!document.hidden && !document.querySelector('dialog[open]')) await cargarPCs({ automatica: true });
            actualizarAutomaticamente();
        }, 15000);
    }
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && !document.querySelector('dialog[open]')) cargarPCs({ automatica: true });
    });
    window.addEventListener('pagehide', () => { clearTimeout(temporizador); consultaPCs?.abort(); consultaSalas?.abort(); });
    window.addEventListener('pageshow', actualizarAutomaticamente);
    $('actualizarPCs').addEventListener('click', cargarPCs);
    $('reintentarPCs').addEventListener('click', cargarPCs);
    $('buscarPC').addEventListener('input', () => { if (!cargando) renderizar(); });
    $('boxPC').addEventListener('change', () => { if (!cargando) renderizar(); });
    $('crearPC').addEventListener('click', () => abrirVinculacion());
    function bloqueo(id, busy) {
        $(id).querySelectorAll('button, input, select').forEach(el => { el.disabled = busy; });
        $(id).setAttribute('aria-busy', String(busy));
    }
    function mostrarCredencial(data) {
        if (typeof data.pairing_code !== 'string' || !/^[A-HJ-NP-Z2-9]{5}$/.test(data.pairing_code)) throw new Error('missing code');
        $('equipoCredencialPC').textContent = data.name.trim().toLocaleLowerCase('es') === boxNombre(data.box).toLocaleLowerCase('es') ? data.name : `${data.name} · ${boxNombre(data.box)}`;
        $('servidorCredencialPC').textContent = window.location.origin;
        $('secretoPC').value = data.pairing_code;
        $('vencimientoCodigoPC').textContent = `Válido hasta ${fecha(data.expires_at)} · Chile`;
        $('estadoCopiaPC').textContent = '';
        abrir('dialogoCredencialPC', $('copiarCredencialPC'));
    }
    $('formularioPC').addEventListener('submit', async e => {
        e.preventDefault();
        if (mutando) return;
        const name = $('nombrePC').value.trim();
        if (!name) { mensaje('errorFormularioPC', 'Escribe un nombre para reconocer este PC.'); $('nombrePC').focus(); return; }
        mutando = true; bloqueo('dialogoPC', true); mensaje('errorFormularioPC', '');
        $('guardarPC').textContent = 'Generando código…';
        let creada = false;
        try {
            const data = await leerRespuesta(await apiPost(`${endpoint}/alta`, { name, box: $('salaPC').value }));
            mostrarCredencial(data); creada = true; $('dialogoPC').close();
        } catch (error) {
            mensaje('errorFormularioPC', error.estado === 409 ? 'No se puede instalar en ese box. Actualiza la pantalla y solicita una revisión técnica si el problema continúa.' : error.estado === 403 ? 'Tu usuario no tiene permiso de administrador.' : 'No se confirmó el alta. Comprueba el listado antes de volver a crear el PC; si ya existe, genera otro código desde su tarjeta.');
        } finally {
            mutando = false; bloqueo('dialogoPC', false); $('guardarPC').textContent = 'Preparar instalación';
            if (creada) { $('copiarCredencialPC').focus(); await cargarPCs(); }
        }
    });
    function confirmar(pc, accion) {
        objetivo = { pc, accion };
        const otroCodigo = ['pending_pairing', 'pairing_expired'].includes(pc.credential_state);
        const tituloRenovacion = otroCodigo ? 'Generar otro código' : 'Reinstalar o reemplazar PC';
        $('tituloAccionPC').textContent = accion === 'cancelar-instalacion' ? 'Cancelar instalación pendiente' : accion === 'renovar' ? tituloRenovacion : 'Deshabilitar acceso';
        $('descripcionAccionPC').textContent = accion === 'cancelar-instalacion'
            ? `Se cancelará la instalación pendiente de ${pc.name}. Su acceso actual y su historial se conservan.` : accion === 'renovar'
            ? `Prepara un código para que el técnico instale o recupere ${pc.name}. El acceso actual se mantiene hasta que la nueva instalación se confirme. Su identidad, box e historial se conservan. Una caída de Internet se recupera automáticamente y no requiere esta acción.`
            : `Se deshabilitará inmediatamente el acceso de ${pc.name} y se cancelarán sus instalaciones pendientes. No podrá enviar audio ni recibir órdenes hasta que un técnico complete una nueva instalación. Su identidad e historial se conservan.`;
        $('confirmarAccionPC').textContent = accion === 'cancelar-instalacion' ? 'Cancelar instalación' : accion === 'renovar' ? (otroCodigo ? 'Generar código' : 'Preparar instalación') : 'Deshabilitar acceso';
        mensaje('errorAccionPC', ''); abrir('dialogoAccionPC');
    }
    $('confirmarAccionPC').addEventListener('click', async () => {
        if (mutando || !objetivo) return;
        const { pc, accion } = objetivo;
        mutando = true; bloqueo('dialogoAccionPC', true); mensaje('errorAccionPC', '');
        let completada = false;
        try {
            const data = await leerRespuesta(await apiPost(`${endpoint}/${encodeURIComponent(pc.agent_id)}/${accion === 'renovar' ? 'vinculacion' : accion}`, {}));
            if (accion === 'renovar') mostrarCredencial(data);
            completada = true; $('dialogoAccionPC').close();
        } catch (error) {
            mensaje('errorAccionPC', error.estado === 403 ? 'Tu usuario no tiene permiso de administrador.' : 'No se confirmó la operación. Actualiza el listado para comprobar el estado. Si no recibiste el código, genera otro.');
        } finally {
            mutando = false; bloqueo('dialogoAccionPC', false);
            if (completada) { if (accion === 'renovar') $('copiarCredencialPC').focus(); await cargarPCs(); }
        }
    });
    $('copiarCredencialPC').addEventListener('click', async () => {
        try { await navigator.clipboard.writeText($('secretoPC').value); $('estadoCopiaPC').textContent = 'Código copiado.'; }
        catch { $('secretoPC').focus(); $('secretoPC').select(); $('estadoCopiaPC').textContent = 'Copia el texto seleccionado con Ctrl+C o ⌘C.'; }
    });
    $('cerrarCredencialPC').addEventListener('click', () => { borrarCredencial(); $('dialogoCredencialPC').close(); });
    $('dialogoCredencialPC').addEventListener('cancel', borrarCredencial);
    function borrarCredencial() { $('secretoPC').value = ''; }
    $('dialogoCredencialPC').addEventListener('close', borrarCredencial);
    window.addEventListener('pagehide', () => { borrarCredencial(); if ($('dialogoCredencialPC').open) $('dialogoCredencialPC').close(); });

    function abrirHistorial(pc) {
        historialPC = pc; pagina = 1; filtros = {};
        $('filtrosHistorialPC').reset(); $('hastaHistorialPC').setCustomValidity('');
        $('tituloHistorialPC').textContent = `Historial de ${pc.name}`;
        $('identidadHistorialPC').textContent = `${pc.name} · ${boxNombre(pc.box)}`;
        abrir('dialogoHistorialPC'); cargarHistorial();
    }
    const calidad = q => ({ reported: 'Informado por el PC', estimated: 'Tiempo estimado', unknown: 'Tiempo desconocido' })[q] || 'Tiempo desconocido';
    function incidente(item) {
        const article = nodos('article', null, 'pcs-incidente');
        const header = nodos('header');
        const source = item.source === 'agent_reported' ? 'Registrado por el PC' : 'Inferido por el servidor';
        header.append(nodos('h3', `${boxNombre(item.box)} · ${String(item.channel || '').toUpperCase()} · ${item.active ? 'Sin recuperación registrada' : 'Recuperado'}`), nodos('span', source, 'pc-badge'));
        const details = nodos('dl', null, 'pc-datos');
        dato(details, 'Inicio · Chile', item.started_at ? fecha(item.started_at) : 'Desconocido').append(nodos('small', calidad(item.start_time_quality)));
        dato(details, 'Recuperación · Chile', item.recovered_at ? fecha(item.recovered_at) : item.active ? 'Sin registrar' : 'Desconocida').append(nodos('small', calidad(item.recovery_time_quality)));
        dato(details, 'Duración', numero(item.duration_ms) ? duracion(item.duration_ms / 1000) : 'Desconocida').append(nodos('small', item.source === 'server_inferred' && item.duration_ms != null ? (item.active ? 'Estimada hasta esta consulta' : 'Estimada') : 'Según tiempos informados'));
        dato(details, 'Causa conocida', causas[item.cause] || 'Causa desconocida');
        dato(details, 'Detectado / recibido · Chile', fecha(item.received_at));
        article.append(header, details);
        return article;
    }
    async function cargarHistorial() {
        consultaHistorial?.abort();
        const controller = new AbortController(); consultaHistorial = controller;
        $('listaHistorialPC').replaceChildren(); $('listaHistorialPC').setAttribute('aria-busy', 'true');
        $('anteriorHistorialPC').disabled = $('siguienteHistorialPC').disabled = true;
        $('reintentarHistorialPC').hidden = true; $('paginaHistorialPC').textContent = '';
        mensaje('estadoHistorialPC', 'Cargando historial…', 'carga');
        try {
            const params = new URLSearchParams({ ...filtros, page: String(pagina), page_size: '10' });
            const data = await apiGetDatos(`${endpoint}/${encodeURIComponent(historialPC.agent_id)}/historial?${params}`, { signal: controller.signal, cache: 'no-store' });
            if (controller.signal.aborted) return;
            if (!Array.isArray(data?.results) || !Number.isInteger(data.pagination?.total_pages)) throw new Error('shape');
            totalPaginas = data.pagination.total_pages;
            $('listaHistorialPC').replaceChildren(...data.results.map(incidente));
            mensaje('estadoHistorialPC', data.results.length ? '' : 'No hay incidentes registrados para este PC con los filtros seleccionados.', 'vacio');
            $('paginaHistorialPC').textContent = totalPaginas ? `Página ${pagina} de ${totalPaginas} · ${data.pagination.total} incidentes` : '0 incidentes';
            $('anteriorHistorialPC').disabled = pagina <= 1;
            $('siguienteHistorialPC').disabled = pagina >= totalPaginas;
        } catch (error) {
            if (controller.signal.aborted) return;
            mensaje('estadoHistorialPC', 'No se pudo consultar el historial. Revisa los filtros y reintenta.', 'error');
            $('reintentarHistorialPC').hidden = false;
        } finally { if (consultaHistorial === controller) $('listaHistorialPC').setAttribute('aria-busy', 'false'); }
    }
    $('filtrosHistorialPC').addEventListener('submit', e => {
        e.preventDefault();
        const desde = $('desdeHistorialPC').value, hasta = $('hastaHistorialPC').value;
        if (desde && hasta && desde > hasta) { $('hastaHistorialPC').setCustomValidity('La fecha final debe ser igual o posterior a la inicial.'); $('hastaHistorialPC').reportValidity(); return; }
        filtros = {};
        if (desde) filtros.desde = desde;
        if (hasta) filtros.hasta = hasta;
        if ($('boxHistorialPC').value) filtros.box = $('boxHistorialPC').value;
        pagina = 1; cargarHistorial();
    });
    ['desdeHistorialPC', 'hastaHistorialPC'].forEach(id => $(id).addEventListener('input', () => $('hastaHistorialPC').setCustomValidity('')));
    $('limpiarHistorialPC').addEventListener('click', () => { $('filtrosHistorialPC').reset(); $('hastaHistorialPC').setCustomValidity(''); filtros = {}; pagina = 1; cargarHistorial(); });
    $('reintentarHistorialPC').addEventListener('click', cargarHistorial);
    $('anteriorHistorialPC').addEventListener('click', () => { if (pagina > 1) { pagina--; cargarHistorial(); } });
    $('siguienteHistorialPC').addEventListener('click', () => { if (pagina < totalPaginas) { pagina++; cargarHistorial(); } });
    $('dialogoHistorialPC').addEventListener('close', () => consultaHistorial?.abort());
    cargarPCs();
    actualizarAutomaticamente();
})();

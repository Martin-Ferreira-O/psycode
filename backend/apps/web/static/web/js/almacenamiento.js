(() => {
    const porId = id => document.getElementById(id);
    const estado = porId('estadoAlmacenamiento');
    const datos = porId('datosAlmacenamiento');
    const actualizar = porId('actualizarAlmacenamiento');
    const liberar = porId('previsualizarLimpieza');
    const confirmar = porId('confirmarLimpieza');
    const cancelar = porId('cancelarLimpieza');
    const dialogo = porId('vistaPreviaLimpieza');
    let token = null;
    let ocupado = false;
    let vencimiento;
    const bytes = valor => {
        if (!Number.isFinite(valor)) return '—';
        const unidades = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
        let indice = 0;
        while (valor >= 1024 && indice < unidades.length - 1) { valor /= 1024; indice++; }
        return `${new Intl.NumberFormat('es-CL', { maximumFractionDigits: 1 }).format(valor)} ${unidades[indice]}`;
    };
    const archivos = cantidad => `${cantidad} ${cantidad === 1 ? 'archivo' : 'archivos'}`;
    const fecha = valor => valor ? new Date(valor).toLocaleString('es-CL') : 'Sin ejecuciones registradas';
    const resultados = { success: 'Completada', partial: 'Completada con fallos', failure: 'Fallida', interrupted: 'Interrumpida; se reintentará', running: 'En ejecución' };
    const protecciones = { minimo_24_horas: 'conservación mínima de 24 h', analisis_activo: 'análisis activo', recuperable: 'procesamiento recuperable', temporal_reciente: 'carga reciente', archivo_en_uso: 'archivo en uso' };
    const mensaje = texto => { estado.hidden = false; estado.textContent = texto; };
    function bloquear(valor) {
        ocupado = valor;
        actualizar.disabled = liberar.disabled = cancelar.disabled = valor;
        confirmar.disabled = valor || !token;
        datos.setAttribute('aria-busy', String(valor));
    }
    async function solicitar(ruta, cuerpo) {
        return solicitarJson(`/api/v1/almacenamiento${ruta}`, cuerpo === undefined ? {} : {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo)
        }, apiRequest);
    }
    function pintar(info) {
        porId('espacioOcupado').textContent = bytes(info.used_bytes);
        porId('espacioDisponible').textContent = bytes(info.available_bytes);
        porId('espacioGestionado').textContent = bytes(info.managed_bytes);
        porId('espacioLiberable').textContent = bytes(info.reclaimable_bytes);
        porId('espacioProtegido').textContent = `${bytes(info.protected_bytes)} · ${archivos(info.protected_files)}`;
        porId('motivosProteccion').textContent = Object.entries(info.reasons || {}).map(([razon, cantidad]) => `${cantidad}: ${protecciones[razon] || 'protegidos'}`).join(' · ') || 'No hay archivos protegidos en este momento.';
        const ultima = info.last_run;
        porId('ultimaLimpieza').textContent = ultima ? fecha(ultima.started_at) : 'Aún no se ha ejecutado';
        porId('resultadoLimpieza').textContent = ultima ? `${resultados[ultima.outcome] || ultima.outcome} · ${bytes(ultima.freed_bytes)} liberados · ${ultima.failures} fallos` : 'Pendiente';
        porId('proximaLimpieza').textContent = `${fecha(info.next_run_at)} · cada 15 minutos`;
        porId('retrasoLimpieza').textContent = info.delay_seconds > 0 ? `${Math.ceil(info.delay_seconds / 60)} minutos de retraso. Revisa el servicio de limpieza.` : 'Sin retraso';
        porId('pendientesLimpieza').textContent = `${info.pending_deletions} borrados pendientes · ${info.intervention_deletions} requieren intervención · ${info.stale_active_jobs || 0} análisis demorados · ${info.review_jobs} trabajos en revisión · ${info.expired_jobs} vencidos · ${info.audit_pending} registros pendientes de bitácora.`;
        porId('cifradoAlmacenamiento').textContent = info.encryption?.verified ? 'Cifrado de volúmenes y protección local de claves verificados.' : 'Cifrado o protección de claves sin verificar. Revisa la verificación del almacenamiento antes de procesar material sensible.';
        datos.hidden = false;
    }
    function errorTexto(error) {
        if (error?.estado === 403) return 'Solo los administradores pueden acceder al almacenamiento del servidor.';
        if (error?.estado === 409) return 'La vista previa venció o hay otra limpieza activa. Actualiza el estado y solicita otra vista previa.';
        return 'No se pudo completar la solicitud. Actualiza el estado antes de volver a intentar la limpieza.';
    }
    async function cargar(anuncio = '') {
        if (ocupado) return;
        bloquear(true);
        if (!anuncio) mensaje('Consultando almacenamiento…');
        try {
            pintar(await solicitar(''));
            if (anuncio) mensaje(anuncio); else estado.hidden = true;
        } catch (error) {
            if (error?.codigo !== 'SESION_FINALIZADA') mensaje(errorTexto(error));
            datos.hidden = true;
        } finally { bloquear(false); }
    }
    async function previsualizar() {
        if (ocupado) return;
        token = null;
        bloquear(true);
        mensaje('Calculando vista previa…');
        try {
            const vista = await solicitar('/vista-previa', {});
            token = vista.preview_token;
            porId('resumenVistaPrevia').textContent = `Se podrán liberar ${bytes(vista.preview_bytes)} en ${archivos(vista.preview_files)}. Permanecerán protegidos ${bytes(vista.protected_bytes)}. Las alertas y los extractos seguirán disponibles.`;
            porId('errorVistaPrevia').hidden = true;
            estado.hidden = true;
            dialogo.showModal();
            clearTimeout(vencimiento);
            vencimiento = setTimeout(() => {
                token = null;
                confirmar.disabled = true;
                porId('errorVistaPrevia').textContent = 'La vista previa venció. Cancela y solicita otra.';
                porId('errorVistaPrevia').hidden = false;
            }, vista.expires_in_seconds * 1000);
        } catch (error) { mensaje(errorTexto(error)); }
        finally { bloquear(false); }
    }
    async function limpiar() {
        if (ocupado || !token) return;
        bloquear(true);
        const elegido = token;
        token = null;
        clearTimeout(vencimiento);
        let anuncio;
        try {
            const resultado = await solicitar('/liberar', { preview_token: elegido });
            anuncio = `${bytes(resultado.freed_bytes)} liberados · ${archivos(resultado.removed)} ${resultado.removed === 1 ? "eliminado" : "eliminados"} · ${resultado.failures} fallos · ${resultado.protected} protegidos al revalidar. Los borrados fallidos se reintentarán automáticamente.`;
        } catch (error) { anuncio = errorTexto(error); }
        finally {
            dialogo.close();
            bloquear(false);
        }
        await cargar(anuncio);
    }
    actualizar.addEventListener('click', () => cargar());
    liberar.addEventListener('click', previsualizar);
    confirmar.addEventListener('click', limpiar);
    cancelar.addEventListener('click', () => dialogo.close());
    dialogo.addEventListener('cancel', evento => { if (ocupado) evento.preventDefault(); });
    dialogo.addEventListener('close', () => { token = null; clearTimeout(vencimiento); liberar.focus(); });
    cargar();
    setInterval(() => { if (!document.hidden && !dialogo.open) cargar(); }, 60000);
})();

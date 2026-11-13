import { useEffect, useRef, useState } from 'react';
import { apiGetDatos } from '../api.js';
import { Badge, Button, Dialog, Icon } from '../ui.jsx';
import { BoxOptions, Dato, Installer } from './cards.jsx';
import { PCS_URL, boxNombre, calidad, causaIncidente, codigoPendiente, duracion, fecha, numero } from './model.js';

export function CrearPCDialog({ initialBox, boxes, salasConsultadas, busy, error, onClose, onSubmit, returnFocusRef }) {
    const [name, setName] = useState(initialBox ? boxNombre(initialBox) : '');
    const [box, setBox] = useState(initialBox || '');
    const [validacion, setValidacion] = useState('');
    const nombreRef = useRef(null);
    const selectedBox = boxes.includes(box) ? box : boxes[0] || '';

    function submit(event) {
        event.preventDefault();
        if (busy || !selectedBox) return;
        const nombre = name.trim();
        if (!nombre) {
            setValidacion('Escribe un nombre para reconocer este PC.');
            nombreRef.current.focus();
            return;
        }
        setValidacion('');
        onSubmit({ name: nombre, box: selectedBox });
    }

    const ayuda = boxes.length
        ? 'La configuración del agente se completa en el computador con un código temporal.'
        : salasConsultadas
            ? 'Todos los boxes disponibles ya tienen un PC o requieren revisión. Para reemplazar uno, utiliza «Instalación y acceso» en su tarjeta; así conserva su identidad e historial.'
            : 'No se pudo consultar qué boxes están disponibles. Cierra este formulario y pulsa Actualizar para volver a intentarlo.';

    return (
        <Dialog id="dialogoPC" open onClose={onClose} className="pcs-dialogo" title="Crear nuevo PC"
            busy={busy} aria-busy={busy} aria-describedby="descripcionDialogoPC"
            initialFocusRef={nombreRef} returnFocusRef={returnFocusRef}>
            <div className="pcs-dialogo-cabecera">
                <h2>Crear nuevo PC</h2>
                <Button variant="ghost" iconOnly aria-label="Cerrar formulario" disabled={busy} onClick={onClose}>
                    <Icon name="close" />
                </Button>
            </div>
            <p id="descripcionDialogoPC" className="pcs-ayuda">
                Elige el box e introduce un nombre para reconocer el computador. El técnico completará la instalación una sola vez.
            </p>
            <p id="salaFormularioPC" className="pcs-aviso">{ayuda}</p>
            <form id="formularioPC" onSubmit={submit}>
                <label className="pcs-campo">
                    Box asignado
                    <select id="salaPC" name="box" required value={selectedBox} disabled={busy || !boxes.length}
                        onChange={event => setBox(event.target.value)}>
                        <BoxOptions boxes={boxes} placeholder={boxes.length ? '' : 'Sin boxes disponibles'} />
                    </select>
                </label>
                <label className="pcs-campo">
                    Nombre reconocible
                    <input id="nombrePC" ref={nombreRef} name="name" required maxLength={100} autoComplete="off"
                        value={name} disabled={busy} placeholder="Ej. Recepción · PC Box 3"
                        onChange={event => { setName(event.target.value); setValidacion(''); }} />
                </label>
                {(validacion || error) && <p id="errorFormularioPC" className="pcs-error" role="alert">{validacion || error}</p>}
                <div className="pcs-dialogo-acciones">
                    <Button disabled={busy} onClick={onClose}>Cancelar</Button>
                    <Button id="guardarPC" type="submit" variant="primary" busy={busy} busyLabel="Generando código…"
                        disabled={!boxes.length}>
                        Preparar instalación
                    </Button>
                </div>
            </form>
        </Dialog>
    );
}

export function RenombrarPCDialog({ pc, busy, error, onClose, onSubmit, returnFocusRef }) {
    const [name, setName] = useState(pc.name);
    const [validacion, setValidacion] = useState('');
    const nombreRef = useRef(null);

    function submit(event) {
        event.preventDefault();
        if (busy) return;
        const nombre = name.trim();
        if (!nombre) {
            setValidacion('Escribe un nombre para el PC.');
            nombreRef.current.focus();
            return;
        }
        setValidacion('');
        onSubmit({ name: nombre });
    }

    return (
        <Dialog open onClose={onClose} className="pcs-dialogo" title="Cambiar nombre del PC"
            busy={busy} aria-describedby="boxRenombrarPC" initialFocusRef={nombreRef} returnFocusRef={returnFocusRef}>
            <h2>Cambiar nombre del PC</h2>
            <p id="boxRenombrarPC" className="pcs-ayuda">{boxNombre(pc.box)}</p>
            <form onSubmit={submit}>
                <label className="pcs-campo">
                    Nombre del PC
                    <input ref={nombreRef} name="name" required maxLength={100} autoComplete="off"
                        value={name} disabled={busy} aria-invalid={Boolean(validacion) || undefined}
                        aria-describedby={validacion || error ? 'errorRenombrarPC' : undefined}
                        onChange={event => { setName(event.target.value); setValidacion(''); }} />
                </label>
                {(validacion || error) && <p id="errorRenombrarPC" className="pcs-error" role="alert">{validacion || error}</p>}
                <div className="pcs-dialogo-acciones">
                    <Button disabled={busy} onClick={onClose}>Cancelar</Button>
                    <Button type="submit" variant="primary" busy={busy} busyLabel="Guardando…">Guardar nombre</Button>
                </div>
            </form>
        </Dialog>
    );
}

function detalleAccion(pc, accion) {
    if (accion === 'cancelar-instalacion') {
        return {
            title: 'Cancelar instalación pendiente', confirm: 'Cancelar instalación', cancel: 'Volver',
            descripcion: pc.initial_installation
                ? `Se invalidará el código de ${pc.name} y el box quedará disponible para registrar un PC.`
                : `Se cancelará la instalación pendiente de ${pc.name}. Su acceso actual y su historial se conservan.`,
        };
    }
    if (accion === 'renovar') {
        const otroCodigo = pc.initial_installation || codigoPendiente(pc);
        return {
            title: otroCodigo ? 'Generar otro código' : 'Reinstalar o reemplazar PC',
            confirm: otroCodigo ? 'Generar código' : 'Preparar instalación',
            cancel: 'Cancelar',
            descripcion: pc.initial_installation
                ? `Se generará un nuevo código para vincular ${pc.name}. El código anterior dejará de funcionar.`
                : `Prepara un código para que el técnico instale o recupere ${pc.name}. El acceso actual se mantiene hasta que la nueva instalación se confirme. Su identidad, box e historial se conservan. Una caída de Internet se recupera automáticamente y no requiere esta acción.`,
        };
    }
    return {
        title: 'Deshabilitar acceso', confirm: 'Deshabilitar acceso', cancel: 'Cancelar',
        descripcion: `Se deshabilitará inmediatamente el acceso de ${pc.name} y se cancelarán sus instalaciones pendientes. No podrá enviar audio ni recibir órdenes hasta que un técnico complete una nueva instalación. Su identidad e historial se conservan.`,
    };
}

export function AccionPCDialog({ pc, action, busy, error, onClose, onConfirm, returnFocusRef }) {
    const cancelRef = useRef(null);
    const { title, confirm, cancel, descripcion } = detalleAccion(pc, action);
    return (
        <Dialog id="dialogoAccionPC" open onClose={onClose} className="pcs-dialogo" title={title}
            busy={busy} aria-busy={busy} aria-describedby="descripcionAccionPC"
            initialFocusRef={cancelRef} returnFocusRef={returnFocusRef}>
            <h2>{title}</h2>
            <p id="descripcionAccionPC">{descripcion}</p>
            {error && <p id="errorAccionPC" className="pcs-error" role="alert">{error}</p>}
            <div className="pcs-dialogo-acciones">
                <Button id="volverAccionPC" ref={cancelRef} disabled={busy} onClick={onClose}>{cancel}</Button>
                <Button id="confirmarAccionPC" variant={action === 'renovar' ? 'primary' : 'danger'}
                    busy={busy} busyLabel="Procesando…" onClick={onConfirm}>{confirm}</Button>
            </div>
        </Dialog>
    );
}

export function CredencialPCDialog({ credential, config, onClose, onExpire, returnFocusRef }) {
    const copyRef = useRef(null);
    const closeRef = useRef(null);
    const inputRef = useRef(null);
    const [copyStatus, setCopyStatus] = useState(null);
    const code = credential?.pairing_code || '';
    const expiresAt = credential?.expires_at;
    const expired = Boolean(credential && !code);
    const box = boxNombre(credential?.box);
    const identidad = credential?.name.trim().toLocaleLowerCase('es') === box.toLocaleLowerCase('es')
        ? credential.name : `${credential?.name ?? ''} · ${box}`;

    useEffect(() => {
        if (!code) return;
        const timer = window.setTimeout(onExpire, Math.max(0, Date.parse(expiresAt) - Date.now()));
        return () => window.clearTimeout(timer);
    }, [code, expiresAt, onExpire]);

    useEffect(() => {
        if (!credential) setCopyStatus(null);
        if (expired) closeRef.current?.focus({ preventScroll: true });
    }, [credential, expired]);

    async function copiar() {
        if (!code) return;
        try {
            await navigator.clipboard.writeText(code);
            if (inputRef.current?.value === code) setCopyStatus('Código copiado.');
        } catch {
            if (inputRef.current?.value !== code) return;
            inputRef.current.focus();
            inputRef.current.select();
            setCopyStatus('Copia el texto seleccionado con Ctrl+C o ⌘C.');
        }
    }

    return (
        <Dialog id="dialogoCredencialPC" open={Boolean(credential)} onClose={onClose} className="pcs-dialogo"
            title="Código temporal" aria-describedby="avisoCredencialPC"
            initialFocusRef={copyRef} returnFocusRef={returnFocusRef}>
            <p className="pcs-eyebrow">INSTALACIÓN INICIAL</p>
            <h2>Código temporal</h2>
            <p>{credential && identidad}</p>
            <p id="avisoCredencialPC" className="pcs-aviso">
                En el asistente de Psycode Agent, introduce el servidor <strong id="servidorCredencialPC">{window.location.origin}</strong> y el código. Pulsa «Vincular e iniciar».{' '}
                {credential && !credential.initial_installation && 'El acceso actual del PC se conserva hasta confirmar la instalación.'}
            </p>
            <label className="pcs-campo">
                Código de instalación
                <input id="secretoPC" ref={inputRef} className="pcs-codigo" readOnly spellCheck={false} autoComplete="off" value={code} />
            </label>
            <p className="pcs-ayuda" role="status">
                {expired ? 'El código venció.' : credential && `Válido hasta ${fecha(expiresAt)} · Chile`}
            </p>
            <div className="pcs-acciones">
                <Button id="copiarCredencialPC" ref={copyRef} disabled={!code} onClick={copiar}>Copiar código</Button>
                <p className="pcs-ayuda" role="status">{code && copyStatus}</p>
            </div>
            <p className="pcs-ayuda">
                {credential?.initial_installation
                    ? 'Si el código vence antes de vincular el PC, el box volverá a quedar disponible.'
                    : 'Si el código vence, puedes preparar otro desde «Instalación y acceso» en la tarjeta del PC.'}
            </p>
            <Installer config={config} />
            <div className="pcs-dialogo-acciones">
                <Button id="cerrarCredencialPC" ref={closeRef} variant="primary" onClick={onClose}>Listo, cerrar</Button>
            </div>
        </Dialog>
    );
}

function Incidente({ item }) {
    const inferido = item.source === 'server_inferred';
    let notaDuracion = 'Según tiempos informados';
    if (inferido && item.duration_ms != null) notaDuracion = item.active ? 'Estimada hasta esta consulta' : 'Estimada';

    return (
        <article className="pcs-incidente">
            <header>
                <h3>{boxNombre(item.box)} · {String(item.channel || '').toUpperCase()} · {item.active ? 'Sin recuperación registrada' : 'Recuperado'}</h3>
                <Badge className="pc-badge">{item.source === 'agent_reported' ? 'Registrado por el PC' : 'Inferido por el servidor'}</Badge>
            </header>
            <dl className="pc-datos">
                <Dato titulo="Inicio · Chile" nota={calidad(item.start_time_quality)}>
                    {item.started_at ? fecha(item.started_at) : 'Desconocido'}
                </Dato>
                <Dato titulo="Recuperación · Chile" nota={calidad(item.recovery_time_quality)}>
                    {item.recovered_at ? fecha(item.recovered_at) : item.active ? 'Sin registrar' : 'Desconocida'}
                </Dato>
                <Dato titulo="Duración" nota={notaDuracion}>{numero(item.duration_ms) ? duracion(item.duration_ms / 1000) : 'Desconocida'}</Dato>
                <Dato titulo="Causa conocida">{causaIncidente(item.cause)}</Dato>
                <Dato titulo="Detectado / recibido · Chile">{fecha(item.received_at)}</Dato>
            </dl>
        </article>
    );
}

export function HistorialPCDialog({ pc, boxes, onClose, returnFocusRef }) {
    const [consulta, setConsulta] = useState({ page: 1, filters: {} });
    const [historial, setHistorial] = useState({ estado: 'carga' });
    const closeRef = useRef(null);
    const hastaRef = useRef(null);
    const formRef = useRef(null);
    const { page, filters } = consulta;
    const { estado, data } = historial;

    useEffect(() => {
        const controller = new AbortController();
        let vigente = true;
        const timer = window.setTimeout(() => controller.abort(), 10000);
        const params = new URLSearchParams({ ...consulta.filters, page: String(consulta.page), page_size: '10' });
        apiGetDatos(`${PCS_URL}/${encodeURIComponent(pc.agent_id)}/historial?${params}`, { signal: controller.signal, cache: 'no-store' })
            .then(data => {
                if (!vigente) return;
                if (!Array.isArray(data?.results) || !Number.isInteger(data.pagination?.total_pages)) throw new Error('Historial inválido');
                setHistorial({ estado: data.results.length ? 'ok' : 'vacio', data });
            })
            .catch(() => { if (vigente) setHistorial({ estado: 'error' }); })
            .finally(() => window.clearTimeout(timer));
        return () => {
            vigente = false;
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [consulta, pc.agent_id]);

    function cargar(nextPage = page, nextFilters = filters) {
        setHistorial({ estado: 'carga' });
        setConsulta({ page: nextPage, filters: nextFilters });
    }

    function filtrar(event) {
        event.preventDefault();
        const campos = new FormData(event.currentTarget);
        const desde = campos.get('desde');
        const hasta = campos.get('hasta');
        if (desde && hasta && desde > hasta) {
            hastaRef.current.setCustomValidity('La fecha final debe ser igual o posterior a la inicial.');
            hastaRef.current.reportValidity();
            return;
        }
        cargar(1, Object.fromEntries([...campos].filter(([, value]) => value)));
    }

    function limpiar() {
        formRef.current.reset();
        hastaRef.current.setCustomValidity('');
        cargar(1, {});
    }

    const statusText = {
        carga: 'Cargando historial…',
        error: 'No se pudo consultar el historial. Revisa los filtros y reintenta.',
        vacio: 'No hay incidentes registrados para este PC con los filtros seleccionados.',
    };
    const totalPaginas = data?.pagination.total_pages || 0;
    const title = `Historial de ${pc.name}`;

    return (
        <Dialog id="dialogoHistorialPC" open onClose={onClose} className="pcs-dialogo pcs-historial" title={title}
            initialFocusRef={closeRef} returnFocusRef={returnFocusRef}>
            <div className="pcs-dialogo-cabecera">
                <div><p className="pcs-eyebrow">CONECTIVIDAD</p><h2>{title}</h2></div>
                <Button ref={closeRef} variant="ghost" iconOnly aria-label="Cerrar historial" onClick={onClose}>
                    <Icon name="close" />
                </Button>
            </div>
            <p className="pcs-ayuda pcs-id">{pc.name} · {boxNombre(pc.box)}</p>
            <form id="filtrosHistorialPC" ref={formRef} className="pcs-filtros" onSubmit={filtrar}>
                <label className="pcs-campo">
                    Desde<input id="desdeHistorialPC" name="desde" type="date" onChange={() => hastaRef.current.setCustomValidity('')} />
                </label>
                <label className="pcs-campo">
                    Hasta<input id="hastaHistorialPC" name="hasta" type="date" ref={hastaRef} onChange={() => hastaRef.current.setCustomValidity('')} />
                </label>
                <label className="pcs-campo">
                    Box<select id="boxHistorialPC" name="box"><BoxOptions boxes={boxes} /></select>
                </label>
                <Button type="submit">Aplicar filtros</Button>
                <Button id="limpiarHistorialPC" onClick={limpiar}>Limpiar</Button>
            </form>
            <p className="pcs-ayuda">Filtra por fecha de inicio; si se desconoce, se usa la fecha de detección. Horas de Chile continental (America/Santiago).</p>
            <div id="estadoHistorialPC" className="pcs-estado" data-estado={estado} role="status" hidden={estado === 'ok'}>
                {statusText[estado]}
            </div>
            {estado === 'error' && <Button id="reintentarHistorialPC" onClick={() => cargar()}>Reintentar historial</Button>}
            <div id="listaHistorialPC" className="pcs-incidentes" aria-busy={estado === 'carga'}>
                {data?.results.map((item, index) => (
                    <Incidente key={item.outage_id ? `${item.source}:${item.box}:${item.channel}:${item.outage_id}` : index} item={item} />
                ))}
            </div>
            <nav className="pcs-paginacion" aria-label="Paginación del historial">
                <span className="pcs-ayuda" aria-live="polite">
                    {data && (totalPaginas ? `Página ${page} de ${totalPaginas} · ${data.pagination.total} incidentes` : '0 incidentes')}
                </span>
                <div className="pcs-acciones">
                    <Button id="anteriorHistorialPC" disabled={!data || page <= 1} onClick={() => cargar(page - 1)}>Anterior</Button>
                    <Button id="siguienteHistorialPC" disabled={!data || page >= totalPaginas} onClick={() => cargar(page + 1)}>Siguiente</Button>
                </div>
            </nav>
        </Dialog>
    );
}

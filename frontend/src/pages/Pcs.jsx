import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { apiPost, leerRespuesta } from '../api.js';
import { PageHeader } from '../layout.jsx';
import { Button } from '../ui.jsx';
import { BoxOptions, EquipoCard, Installer, SalaCard } from '../pcs/cards.jsx';
import { AccionPCDialog, CrearPCDialog, CredencialPCDialog, HistorialPCDialog } from '../pcs/dialogs.jsx';
import { PCS_URL, boxNombre, compararEquipos, credencialValida, fecha } from '../pcs/model.js';
import { useRegistry } from '../pcs/useRegistry.js';

function mensajeMutacion(error, alta) {
    if (error.estado === 403) return 'Tu usuario no tiene permiso de administrador.';
    if (alta) {
        return error.estado === 409
            ? 'No se puede instalar en ese box. Actualiza la pantalla y solicita una revisión técnica si el problema continúa.'
            : 'No se confirmó el alta. Comprueba el listado antes de volver a crear el PC; si ya existe, genera otro código desde su tarjeta.';
    }
    return [404, 409].includes(error.estado)
        ? 'La instalación cambió. Cierra este diálogo y actualiza el listado para consultar su estado.'
        : 'No se confirmó la operación. Actualiza el listado para comprobar el estado. Si no recibiste el código, genera otro.';
}

export default function Pcs({ config }) {
    const [dialog, setDialog] = useState(null);
    const [busy, setBusy] = useState(false);
    const [mutationError, setMutationError] = useState('');
    const [busqueda, setBusqueda] = useState('');
    const [box, setBox] = useState('');
    const [smileStatus, setSmileStatus] = useState(null);
    const [testing, setTesting] = useState([]);
    const pendingMutation = useRef(null);
    const smileRequests = useRef(new Map());
    const listaRef = useRef(null);
    const createRef = useRef(null);
    const originRef = useRef(null);
    const focusedCard = useRef(null);

    const captureFocus = useCallback(() => {
        const active = document.activeElement;
        if (listaRef.current?.contains(active)) {
            focusedCard.current = { active, box: active.closest('.pc-tarjeta')?.dataset.box };
        }
    }, []);

    const { equipos, salas, salasConsultadas, errorSalas, ultimaConsulta, estado, cargando, cargar, actualizarPrueba } =
        useRegistry({ paused: Boolean(dialog) || busy, beforeCardsChange: captureFocus });

    useLayoutEffect(() => {
        if (!focusedCard.current) return;
        const { active, box: activeBox } = focusedCard.current;
        focusedCard.current = null;
        if (dialog || document.activeElement !== document.body) return;
        const fallback = [...(listaRef.current?.children ?? [])]
            .find(element => element.dataset.box === activeBox)?.querySelector('button:enabled, summary');
        const target = active.isConnected && !active.disabled ? active : fallback || createRef.current;
        target?.focus({ preventScroll: true });
    }, [dialog, equipos, salas]);

    useEffect(() => {
        const requests = smileRequests.current;
        function abortar() {
            pendingMutation.current?.abort();
            pendingMutation.current = null;
            for (const controller of requests.values()) controller.abort();
            requests.clear();
        }
        function limpiarAntesDeSalir() {
            const request = pendingMutation.current;
            abortar();
            flushSync(() => {
                setDialog(current => current?.kind === 'credencial' ? null : current);
                setTesting([]);
                setBusy(false);
                if (request) setMutationError('No se confirmó la operación. Actualiza el listado para comprobar el estado.');
            });
        }

        window.addEventListener('pagehide', limpiarAntesDeSalir);
        return () => {
            abortar();
            window.removeEventListener('pagehide', limpiarAntesDeSalir);
        };
    }, []);

    function abrir(nextDialog, origen) {
        originRef.current = origen;
        setMutationError('');
        setDialog(nextDialog);
    }

    function cerrar() {
        if (pendingMutation.current) return;
        if (!originRef.current?.isConnected || originRef.current.disabled) originRef.current = createRef.current;
        setDialog(null);
    }

    async function mutar(path, body, { alta = false, muestraCredencial = false } = {}) {
        if (pendingMutation.current) return;
        const controller = new AbortController();
        pendingMutation.current = controller;
        setBusy(true);
        setMutationError('');
        const timer = window.setTimeout(() => controller.abort(), 15000);

        try {
            const data = await leerRespuesta(await apiPost(path, body, { signal: controller.signal }));
            if (pendingMutation.current !== controller) return;
            if (muestraCredencial && !credencialValida(data)) throw new Error('Código de instalación inválido');
            setDialog(muestraCredencial ? { kind: 'credencial', data } : null);
            cargar({ reemplazar: true });
        } catch (error) {
            if (pendingMutation.current === controller) setMutationError(mensajeMutacion(error, alta));
        } finally {
            window.clearTimeout(timer);
            if (pendingMutation.current === controller) {
                pendingMutation.current = null;
                setBusy(false);
            }
        }
    }

    function confirmar() {
        const { pc, action } = dialog;
        const path = action === 'renovar' ? 'vinculacion' : action;
        mutar(`${PCS_URL}/${encodeURIComponent(pc.agent_id)}/${path}`, {}, { muestraCredencial: action === 'renovar' });
    }

    const vencerCredencial = useCallback(() => {
        setDialog(current => current?.kind === 'credencial'
            ? { ...current, data: { ...current.data, pairing_code: '' } }
            : current);
        cargar({ automatica: true, reemplazar: true });
    }, [cargar]);

    async function probarSmile(pc, source) {
        const requests = smileRequests.current;
        if (requests.has(pc.agent_id)) return;
        const controller = new AbortController();
        requests.set(pc.agent_id, controller);
        setTesting([...requests.keys()]);
        const timer = window.setTimeout(() => controller.abort(), 10000);

        try {
            const check = await leerRespuesta(await apiPost(
                `${PCS_URL}/${encodeURIComponent(pc.agent_id)}/smile/prueba`,
                { source }, { signal: controller.signal }
            ));
            if (requests.get(pc.agent_id) !== controller) return;
            actualizarPrueba(pc.agent_id, check);
            setSmileStatus({ text: `Prueba solicitada para ${pc.name}. El resultado aparecerá en su tarjeta.` });
        } catch (error) {
            if (requests.get(pc.agent_id) !== controller) return;
            const text = error.estado === 429 ? 'Espera 30 segundos desde la última solicitud.'
                : error.estado === 409 ? 'Comprueba que el colector esté conectado, actualizado y sin otra prueba en curso.'
                    : 'No se confirmó la solicitud. Comprueba el estado en la tarjeta antes de reintentar.';
            setSmileStatus({ text, error: true });
        } finally {
            window.clearTimeout(timer);
            if (requests.get(pc.agent_id) === controller) {
                requests.delete(pc.agent_id);
                setTesting([...requests.keys()]);
            }
        }
    }

    const boxes = [...new Set([...equipos.map(pc => pc.box), ...salas.map(sala => sala.box)])]
        .sort((a, b) => Number(a.slice(4)) - Number(b.slice(4)));
    const selectedBox = boxes.includes(box) ? box : '';
    const query = busqueda.trim().toLocaleLowerCase('es');
    const coincide = (boxEquipo, text) => (!selectedBox || boxEquipo === selectedBox) && text.toLocaleLowerCase('es').includes(query);
    const ocupadas = new Set(equipos.map(pc => pc.box));
    const equiposVisibles = equipos
        .filter(pc => coincide(pc.box, `${pc.name} ${pc.agent_id} ${boxNombre(pc.box)}`))
        .sort(compararEquipos);
    const salasLibres = salas.filter(sala => !ocupadas.has(sala.box) && !sala.existing_pc_id);
    const salasVisibles = salasLibres.filter(sala => coincide(sala.box, `${sala.name} ${boxNombre(sala.box)}`));
    const boxesDisponibles = salasLibres.filter(sala => sala.available && !sala.conflict).map(sala => sala.box);
    const status = estado === 'ok' && !equiposVisibles.length && !salasVisibles.length ? 'vacio' : estado;
    const errorRegistro = estado === 'error' || estado === 'denegado';
    let actualizacion = 'Consulta pendiente';
    if (errorRegistro) actualizacion = ultimaConsulta ? `Información sin actualizar desde ${fecha(ultimaConsulta)} · Chile` : 'Sin datos disponibles';
    else if (ultimaConsulta) actualizacion = `Última consulta: ${fecha(ultimaConsulta)} · Actualización automática`;

    const statusText = {
        carga: ultimaConsulta ? 'Actualizando equipos…' : 'Cargando equipos…',
        error: 'No se pudo actualizar el estado. Se conserva la última información disponible y volveremos a intentarlo automáticamente.',
        denegado: 'Solo un administrador puede consultar esta pantalla.',
        vacio: equipos.length || salas.length
            ? 'No hay salas o equipos que coincidan con los filtros.'
            : 'Todavía no hay equipos ni boxes configurados. La instalación inicial debe completarla el técnico.',
    };

    return (
        <div className="pagina-pcs">
            <PageHeader title="Gestión de PCs" description="Revisa el funcionamiento de los computadores de la clínica y consulta su historial." />
            <section className="pcs-panel" aria-labelledby="tituloRegistro">
                <div className="pcs-toolbar">
                    <div>
                        <h2 id="tituloRegistro">Equipos de la clínica</h2>
                        <p id="actualizacionPCs" className="pcs-ayuda">{actualizacion}</p>
                    </div>
                    <div className="pcs-acciones">
                        <Button id="actualizarPCs" disabled={cargando} onClick={() => cargar()}>Actualizar</Button>
                        <Button id="crearPC" ref={createRef} variant="primary" onClick={event => abrir({ kind: 'crear' }, event.currentTarget)}>
                            Crear nuevo PC
                        </Button>
                    </div>
                </div>
                <div className="pcs-descarga-inicial">
                    <Installer config={config} />
                    {config.installerVersion && (
                        <p className="pcs-ayuda">Puedes ejecutar el instalador y abrir el asistente antes de crear el PC y generar el código.</p>
                    )}
                </div>
                <div className="pcs-filtros">
                    <label className="pcs-campo pcs-busqueda">
                        Buscar sala o equipo
                        <input id="buscarPC" type="search" placeholder="Sala, nombre o identificador" maxLength={100}
                            value={busqueda} onChange={event => setBusqueda(event.target.value)} />
                    </label>
                    <label className="pcs-campo">
                        Box
                        <select id="boxPC" value={selectedBox} onChange={event => setBox(event.target.value)}>
                            <BoxOptions boxes={boxes} />
                        </select>
                    </label>
                    <p id="cantidadPCs" className="pcs-ayuda" aria-live="polite">
                        {equiposVisibles.length} de {equipos.length} PCs registrados
                    </p>
                </div>
                {errorSalas && (
                    <p id="avisoSalasPCs" className="pcs-aviso pc-aviso" role="status">
                        No se pudo actualizar la disponibilidad de boxes. Los equipos se consultan por separado; volveremos a intentarlo automáticamente.
                    </p>
                )}
                <div id="estadoPCs" className="pcs-estado" role="status" data-estado={errorRegistro ? 'error' : status} hidden={status === 'ok'}>
                    {statusText[status]}
                </div>
                {estado === 'error' && <Button id="reintentarPCs" className="pcs-reintento" disabled={cargando} onClick={() => cargar()}>Reintentar</Button>}
                {smileStatus && (
                    <div id="estadoSmilePCs" className="pcs-estado" role="status" data-estado={smileStatus.error ? 'error' : 'exito'}>
                        {smileStatus.text}
                    </div>
                )}
                <div id="listaPCs" className="pcs-lista" ref={listaRef} aria-busy={cargando}>
                    {equiposVisibles.map(pc => (
                        <EquipoCard key={pc.agent_id} pc={pc} testing={testing.includes(pc.agent_id)} onTest={probarSmile}
                            onAction={(target, action, origen) => abrir({ kind: 'accion', pc: target, action }, origen)}
                            onHistory={(target, origen) => abrir({ kind: 'historial', pc: target }, origen)} />
                    ))}
                    {salasVisibles.map(sala => (
                        <SalaCard key={sala.box} sala={sala} onCreate={(initialBox, origen) => abrir({ kind: 'crear', initialBox }, origen)} />
                    ))}
                </div>
            </section>
            <p className="pcs-pie">La captura, la recepción y el procesamiento se muestran por separado. Los datos corresponden a la última consulta.</p>
            {dialog?.kind === 'crear' && (
                <CrearPCDialog initialBox={dialog.initialBox} boxes={boxesDisponibles} salasConsultadas={salasConsultadas}
                    busy={busy} error={mutationError} onClose={cerrar} returnFocusRef={originRef}
                    onSubmit={body => mutar(`${PCS_URL}/alta`, body, { alta: true, muestraCredencial: true })} />
            )}
            {dialog?.kind === 'accion' && (
                <AccionPCDialog pc={dialog.pc} action={dialog.action} busy={busy} error={mutationError}
                    onClose={cerrar} onConfirm={confirmar} returnFocusRef={originRef} />
            )}
            <CredencialPCDialog config={config} credential={dialog?.kind === 'credencial' ? dialog.data : null}
                onClose={cerrar} onExpire={vencerCredencial} returnFocusRef={originRef} />
            {dialog?.kind === 'historial' && (
                <HistorialPCDialog pc={dialog.pc} boxes={boxes} onClose={cerrar} returnFocusRef={originRef} />
            )}
        </div>
    );
}

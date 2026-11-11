import { Badge, Button } from '../ui.jsx';
import {
    boxNombre, codigoPendiente, duracion, espacio, estadoFlujo, estadoSmile,
    fecha, informado, numero, pruebaSmileActiva,
} from './model.js';

export function BoxOptions({ boxes, placeholder = 'Todos los boxes' }) {
    return (
        <>
            {placeholder && <option value="">{placeholder}</option>}
            {boxes.map(box => <option key={box} value={box}>{boxNombre(box)}</option>)}
        </>
    );
}

export function Installer({ config }) {
    if (!config.installerVersion || !config.installerUrl || !config.checksumUrl) {
        return (
            <p className="pcs-aviso" role="status">
                El instalador de Windows x64 no está disponible. Si ya tienes Psycode Agent instalado, puedes vincularlo desde el asistente.
            </p>
        );
    }

    return (
        <div className="pcs-instalador">
            <Button href={config.installerUrl} variant="secondary" target="_blank" rel="noopener">
                Descargar instalador para Windows x64
            </Button>
            <p className="pcs-ayuda">
                Versión {config.installerVersion} · <a href={config.checksumUrl} target="_blank" rel="noopener">Descargar SHA-256</a>
            </p>
        </div>
    );
}

export function Dato({ titulo, children, nota }) {
    return (
        <div>
            <dt>{titulo}</dt>
            <dd>{children}{nota && <small>{nota}</small>}</dd>
        </div>
    );
}

const estadoTone = { online: 'success', pendiente: 'warning', revocado: 'danger' };

function CabeceraTarjeta({ box, nombre, estado, estilo = '' }) {
    return (
        <header className="pc-tarjeta-cabecera">
            <div className="pc-identidad">
                <span className="pc-box">{boxNombre(box).toUpperCase()}</span>
                <h3 className="pc-nombre">{nombre}</h3>
            </div>
            <Badge className={`pc-badge ${estilo}`} tone={estadoTone[estilo]}>{estado}</Badge>
        </header>
    );
}

export function SalaCard({ sala, onCreate }) {
    const estado = sala.conflict ? 'Requiere revisión técnica' : sala.available ? 'Sin PC registrado' : 'Sala deshabilitada';
    const nota = sala.conflict
        ? 'Hay varios equipos asociados a este box. Solicita una revisión técnica.'
        : sala.available
            ? 'Genera un código para vincular el computador de este box.'
            : 'Solicita una revisión técnica para habilitar la sala.';

    return (
        <article className="pc-tarjeta pc-sala" data-box={sala.box}>
            <CabeceraTarjeta box={sala.box} nombre={sala.name} estado={estado} estilo={sala.conflict ? 'pendiente' : ''} />
            <p className="pc-nota">{nota}</p>
            <footer className="pc-tarjeta-pie">
                <Button variant="primary" aria-label={`Crear nuevo PC en ${boxNombre(sala.box)}`}
                    disabled={!sala.available || sala.conflict} onClick={event => onCreate(sala.box, event.currentTarget)}>
                    Crear nuevo PC
                </Button>
            </footer>
        </article>
    );
}

function BotonRenovar({ pc, instalacion, onAction }) {
    const texto = instalacion ? 'Generar otro código' : 'Reinstalar o reemplazar';
    return (
        <Button variant="secondary" disabled={pc.room_available === false}
            aria-label={instalacion ? `${texto} para ${pc.name}` : `${texto} ${pc.name}`}
            onClick={event => onAction(pc, 'renovar', event.currentTarget)}>
            {texto}
        </Button>
    );
}

function InstalacionInicial({ pc, onAction }) {
    return (
        <>
            <CabeceraTarjeta box={pc.box} nombre={pc.name} estado="Pendiente de instalación" estilo="pendiente" />
            <p className="pc-nota">
                {pc.installation_expires_at
                    ? `El técnico puede vincular el PC hasta el ${fecha(pc.installation_expires_at)} (Chile).`
                    : 'El técnico debe vincular el PC con el código temporal.'}
            </p>
            <footer className="pc-tarjeta-pie pc-pendiente-acciones">
                <BotonRenovar pc={pc} instalacion onAction={onAction} />
                <Button variant="danger" aria-label={`Cancelar instalación de ${pc.name}`}
                    onClick={event => onAction(pc, 'cancelar-instalacion', event.currentTarget)}>
                    Cancelar instalación
                </Button>
            </footer>
        </>
    );
}

function TelemetriaPC({ pc, conectado }) {
    let captura = 'Sin datos';
    if (informado(pc, 'capturing') && typeof pc.capturing === 'boolean') {
        captura = pc.capturing ? 'Capturando' : 'Sin captura';
    }
    return (
        <>
            <dl className="pc-datos">
                <Dato titulo="Versión del agente">{pc.version || 'Sin datos'}</Dato>
                <Dato titulo="Última comunicación · Chile">{fecha(pc.last_seen_at)}</Dato>
                <Dato titulo={conectado ? 'Captura informada por el PC' : 'Última captura informada'}>{captura}</Dato>
                <Dato titulo="Último audio recibido de este PC">{fecha(pc.last_audio?.accepted_at)}</Dato>
            </dl>
            <section className="pc-flujo-bloque">
                <h4>Flujo de {boxNombre(pc.box)}</h4>
                <dl className="pc-flujo">
                    <Dato titulo="Captura">{estadoFlujo(pc.capture_status)}</Dato>
                    <Dato titulo="Recepción">{estadoFlujo(pc.reception_status)}</Dato>
                    <Dato titulo="Procesamiento">{estadoFlujo(pc.processing_status)}</Dato>
                </dl>
            </section>
            <dl className="pc-datos pc-capacidad">
                <Dato titulo="Pendientes del PC">
                    {informado(pc, 'pending') && numero(pc.pending) ? pc.pending : 'Sin datos'}
                </Dato>
                <Dato titulo="Disco libre">{espacio(pc.free_bytes)}</Dato>
                <Dato titulo="Autonomía estimada">{duracion(pc.remaining_seconds)}</Dato>
            </dl>
        </>
    );
}

const ayudaOperativa = {
    RECOVERY_REQUIRED: 'Hay una captura pendiente de recuperación. Solicita asistencia técnica; los archivos se conservan.',
    UPLOAD_INTERVENTION: 'Hay envíos que necesitan revisión técnica. Los audios pendientes se conservan.',
    SMILE_UNAVAILABLE: 'La agenda no se ha podido actualizar. Prueba el acceso a Smile o solicita una revisión del perfil.',
};

function AvisosPC({ pc, conectado, instalacion }) {
    const capacidadCritica = pc.storage_warning?.level === 'critical';

    return (
        <>
            {!conectado && pc.active && <p className="pc-nota">Comprueba que el PC esté encendido y tenga Internet. La reconexión es automática.</p>}
            {instalacion && <p className="pc-nota">
                {pc.credential_state === 'pairing_expired'
                    ? 'La instalación no se completó a tiempo. El técnico puede preparar otro código para este mismo PC.'
                    : 'El técnico debe completar la instalación en el computador de este box.'}
            </p>}
            {pc.room_available === false && <p className="pcs-aviso pc-aviso">La sala está deshabilitada. Solicita una revisión técnica antes de utilizarla.</p>}
            {conectado && pc.obs === 'unavailable' && <p className="pcs-aviso pc-aviso">La aplicación de captura no responde. Comprueba que OBS esté abierto en la cuenta de Windows configurada. Si continúa, solicita asistencia técnica.</p>}
            {pc.storage_warning?.active && <p className={`pcs-aviso pc-aviso ${capacidadCritica ? 'critical' : ''}`}>
                {capacidadCritica ? 'Atención: capacidad crítica. Revisa el disco y los envíos pendientes.' : 'Aviso: capacidad baja. Revisa el espacio y la autonomía disponible.'}
            </p>}
            {pc.operational_code && !pc.storage_warning?.active && <p className="pcs-aviso pc-aviso">
                {Object.hasOwn(ayudaOperativa, pc.operational_code) ? ayudaOperativa[pc.operational_code] : 'El equipo informó un problema. Consulta el historial y solicita asistencia técnica si continúa.'}
            </p>}
        </>
    );
}

function ColectorSmile({ pc, conectado, testing, onTest }) {
    if (!Array.isArray(pc.smile_sources) || !pc.smile_sources.length) return null;
    const disabled = !conectado || !pc.smile_check_supported || pruebaSmileActiva(pc.smile_check) || testing;
    return (
        <section className="pc-flujo-bloque">
            <h4>Colector Smile</h4>
            {pc.smile_sources.map(source => {
                const check = pc.smile_check?.source === source ? pc.smile_check : null;
                const nota = !conectado ? 'Colector sin conexión.'
                    : !pc.smile_check_supported ? 'Actualiza el agente para probar el colector.'
                        : estadoSmile(check);
                return (
                    <div className="pc-prueba-smile" key={source}>
                        <p className="pc-nota">{nota}</p>
                        <Button variant="secondary" disabled={disabled} onClick={() => onTest(pc, source)}>
                            {pc.smile_sources.length === 1 ? 'Probar colector' : `Probar colector · ${source}`}
                        </Button>
                    </div>
                );
            })}
        </section>
    );
}

export function EquipoCard({ pc, onAction, onHistory, onTest, testing }) {
    const conectado = pc.connection === 'online';
    const instalacion = codigoPendiente(pc);
    let estado = conectado ? 'Conectado' : 'Sin comunicación';
    let estilo = conectado ? 'online' : '';
    if (instalacion) {
        estado = pc.credential_state === 'pairing_expired' ? 'Código vencido' : 'Pendiente de instalación';
        estilo = 'pendiente';
    } else if (!pc.active) {
        estado = 'Acceso deshabilitado';
        estilo = 'revocado';
    }

    return (
        <article className="pc-tarjeta" data-agent-id={pc.agent_id} data-box={pc.box}>
            {pc.initial_installation ? <InstalacionInicial pc={pc} onAction={onAction} /> : (
                <>
                    <CabeceraTarjeta box={pc.box} nombre={pc.name} estado={estado} estilo={estilo} />
                    <TelemetriaPC pc={pc} conectado={conectado} />
                    <AvisosPC pc={pc} conectado={conectado} instalacion={instalacion} />
                    <ColectorSmile pc={pc} conectado={conectado} testing={testing} onTest={onTest} />
                    <footer className="pc-tarjeta-pie">
                        <Button variant="secondary" aria-label={`Ver historial de ${pc.name}`} onClick={event => onHistory(pc, event.currentTarget)}>
                            Ver historial
                        </Button>
                        <details className="pc-mantenimiento">
                            <summary>Instalación y acceso</summary>
                            <div className="pcs-acciones">
                                <BotonRenovar pc={pc} instalacion={instalacion} onAction={onAction} />
                                <Button variant="danger" aria-label={`Deshabilitar acceso de ${pc.name}`}
                                    disabled={!pc.active && !pc.installation_pending}
                                    onClick={event => onAction(pc, 'revocar', event.currentTarget)}>
                                    Deshabilitar acceso
                                </Button>
                                {pc.installation_pending && (
                                    <Button variant="secondary" onClick={event => onAction(pc, 'cancelar-instalacion', event.currentTarget)}>
                                        Cancelar instalación pendiente
                                    </Button>
                                )}
                            </div>
                        </details>
                    </footer>
                </>
            )}
        </article>
    );
}

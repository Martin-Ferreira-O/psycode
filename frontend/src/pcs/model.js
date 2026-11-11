export const PCS_URL = '/api/v1/pcs';

const dateFormatter = new Intl.DateTimeFormat('es-CL', {
    timeZone: 'America/Santiago',
    dateStyle: 'short',
    timeStyle: 'medium',
});
const numberFormatter = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 1 });

export function fecha(value) {
    if (!value) return 'Sin datos';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Desconocida' : dateFormatter.format(date);
}

export function boxNombre(value) {
    return /^box-[1-9][0-9]{0,11}$/.test(value) ? `Box ${value.slice(4)}` : 'Box desconocido';
}

export const numero = value => Number.isFinite(value) && value >= 0;
export const informado = (pc, campo) => !Array.isArray(pc.telemetry_fields) || pc.telemetry_fields.includes(campo);

export function duracion(seconds) {
    if (!numero(seconds)) return 'Desconocida';
    if (seconds < 60) return `${Math.floor(seconds)} s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
    return `${Math.floor(seconds / 3600)} h ${Math.floor(seconds % 3600 / 60)} min`;
}

export function espacio(bytes) {
    if (!numero(bytes)) return 'Sin datos';
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
    const index = bytes >= 1 ? Math.min(4, Math.floor(Math.log(bytes) / Math.log(1024))) : 0;
    return `${numberFormatter.format(bytes / 1024 ** index)} ${units[index]}`;
}

const estados = {
    no_session: 'Sin sesión', active: 'En curso', started: 'Iniciando', pending: 'Pendiente',
    completed: 'Completado', closed: 'Cerrado', failed: 'Fallido', stopped: 'Detenido',
    stopping: 'Deteniendo', interrupted: 'Interrumpido', receiving: 'Recibiendo', processing: 'Procesando',
    waiting: 'En espera', idle: 'En espera', complete: 'Completo', draining: 'Recibiendo pendientes',
    queued: 'En cola', review: 'Requiere revisión', partial: 'Parcial', delayed: 'Con retraso',
    finished: 'Finalizada', stop_unconfirmed: 'Detención sin confirmar', start_unconfirmed: 'Inicio sin confirmar',
    intervention_required: 'Requiere intervención',
};

const causas = {
    TIMEOUT: 'Tiempo de espera agotado', CONNECTION_ERROR: 'Error de conexión',
    CONNECTION_LOST: 'Conexión perdida', CONNECTION_TIMEOUT: 'Sin mensajes del PC', HTTP_ERROR: 'Error HTTPS',
    DISK_LOW: 'Disco con poco espacio', STORAGE_WARNING: 'Capacidad baja', STORAGE_CRITICAL: 'Capacidad crítica',
    LOCAL_WRITE_FAILED: 'Error al escribir en disco', RECOVERY_REQUIRED: 'Recuperación requerida',
    CREDENTIAL_REVOKED: 'Credencial revocada', CREDENTIAL_RENEWED: 'Credencial renovada',
    CREDENTIAL_INVALIDATED: 'Credencial invalidada',
};

const calidadTiempo = {
    reported: 'Informado por el PC', estimated: 'Tiempo estimado', unknown: 'Tiempo desconocido',
};

const resultadosSmile = {
    ok: 'Acceso a Smile y selector de salas verificados.',
    missing_profile: 'Falta el perfil en este PC. Impórtalo en Psycode Agent → Soporte.',
    source_mismatch: 'El perfil del PC tiene otra fuente. Revisa su asignación e importa el perfil correcto.',
    external_command: 'El perfil usa un comando externo. Esta prueba requiere el extractor integrado.',
    timeout: 'La prueba superó el tiempo de espera. Comprueba la red institucional.',
    failed: 'No se pudo comprobar Smile. Revisa el perfil, la red institucional y el certificado.',
};

export const estadoFlujo = value => Object.hasOwn(estados, value) ? estados[value] : 'Sin información';
export const causaIncidente = value => Object.hasOwn(causas, value) ? causas[value] : 'Causa desconocida';
export const calidad = value => Object.hasOwn(calidadTiempo, value) ? calidadTiempo[value] : 'Tiempo desconocido';
export const pruebaSmileActiva = check => ['queued', 'running'].includes(check?.state);
export const codigoPendiente = pc => ['pending_pairing', 'pairing_expired'].includes(pc.credential_state);

export function estadoSmile(check) {
    if (check?.state === 'queued') return 'Esperando al colector…';
    if (check?.state === 'running') return 'Comprobando acceso a Smile…';
    if (check?.state === 'expired') return 'El colector no devolvió un resultado a tiempo.';
    if (check?.state === 'finished') {
        return Object.hasOwn(resultadosSmile, check.result) ? resultadosSmile[check.result] : 'Resultado no disponible.';
    }
    return 'Sin prueba registrada.';
}

export function compararEquipos(a, b) {
    const conectadoA = a.connection === 'online';
    const conectadoB = b.connection === 'online';
    if (conectadoA !== conectadoB) return conectadoA ? -1 : 1;
    if (conectadoA) return 0;

    const fechaA = Date.parse(a.last_seen_at);
    const fechaB = Date.parse(b.last_seen_at);
    if (Number.isNaN(fechaA)) return Number.isNaN(fechaB) ? 0 : 1;
    if (Number.isNaN(fechaB)) return -1;
    return fechaB - fechaA;
}

export function credencialValida(data) {
    return typeof data?.pairing_code === 'string' && /^[A-HJ-NP-Z2-9]{5}$/.test(data.pairing_code)
        && typeof data.name === 'string'
        && Number.isFinite(Date.parse(data.expires_at));
}

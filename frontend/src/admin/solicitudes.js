import { apiRequest, ErrorSolicitud, leerRespuesta } from "../api.js";

export async function solicitarCambioAdministrativo(url, { method, payload, signal, campos }) {
    const opciones = { method, signal };
    if (payload !== undefined) {
        opciones.headers = { "Content-Type": "application/json" };
        opciones.body = JSON.stringify(payload);
    }

    let respuesta;
    try {
        respuesta = await apiRequest(url, opciones);
    } catch (error) {
        if (error.name === "AbortError") throw error;
        throw new ErrorSolicitud(0, "SIN_CONEXION");
    }

    // Solo las validaciones de campos conocidos se muestran en los formularios.
    if (respuesta?.status === 400) {
        const cuerpo = await respuesta.json().catch(() => null);
        if (cuerpo?.success === false && cuerpo.error?.code === "VALIDATION_ERROR") {
            const detalles = {};
            for (const campo of campos) {
                const mensajes = cuerpo.error.details?.fields?.[campo];
                if (Array.isArray(mensajes)) {
                    detalles[campo] = mensajes.filter((mensaje) => typeof mensaje === "string" && mensaje.trim());
                }
            }
            const error = new ErrorSolicitud(400, "VALIDATION_ERROR");
            error.detalles = { fields: detalles };
            throw error;
        }
    }

    return leerRespuesta(respuesta);
}

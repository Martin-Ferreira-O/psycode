import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { apiGetDatos } from '../api.js';
import { PCS_URL } from './model.js';

function validarEquipos(data) {
    if (!Array.isArray(data) || data.some(pc => !pc || typeof pc.name !== 'string'
        || typeof pc.agent_id !== 'string' || typeof pc.box !== 'string')) {
        throw new Error('Registro de PCs inválido');
    }
    return data;
}

function validarSalas(data) {
    if (!Array.isArray(data) || data.some(room => !room || !(room.room_id == null || typeof room.room_id === 'string')
        || typeof room.name !== 'string' || typeof room.box !== 'string')) {
        throw new Error('Disponibilidad de boxes inválida');
    }
    return data;
}

export function useRegistry({ paused, beforeCardsChange }) {
    const [equipos, setEquipos] = useState([]);
    const [salas, setSalas] = useState([]);
    const [salasConsultadas, setSalasConsultadas] = useState(false);
    const [errorSalas, setErrorSalas] = useState(false);
    const [ultimaConsulta, setUltimaConsulta] = useState(null);
    const [estado, setEstado] = useState('carga');
    const [cargando, setCargando] = useState(true);
    const request = useRef(null);
    const consultaExitosa = useRef(false);
    const pausa = useRef(paused);

    useLayoutEffect(() => {
        pausa.current = paused;
    }, [paused]);

    const cargar = useCallback(async ({ automatica = false, reemplazar = false } = {}) => {
        if (request.current) {
            if (!reemplazar) return;
            request.current.cancelar();
        }
        const equiposController = new AbortController();
        const salasController = new AbortController();
        const limiteEquipos = window.setTimeout(() => equiposController.abort(), 10000);
        const limiteSalas = window.setTimeout(() => salasController.abort(), 10000);
        const consulta = {
            cancelar() {
                equiposController.abort();
                salasController.abort();
                window.clearTimeout(limiteEquipos);
                window.clearTimeout(limiteSalas);
            },
        };
        request.current = consulta;
        const vigente = () => request.current === consulta;
        setCargando(true);
        if (!automatica || !consultaExitosa.current) setEstado('carga');

        // La disponibilidad de salas y el registro se actualizan por separado.
        const consultarSalas = apiGetDatos(`${PCS_URL}/salas`, { cache: 'no-store', signal: salasController.signal })
            .then(validarSalas)
            .then(data => {
                if (!vigente()) return;
                beforeCardsChange();
                setSalas(data);
                setSalasConsultadas(true);
                setErrorSalas(false);
            })
            .catch(() => {
                if (vigente()) setErrorSalas(true);
            })
            .finally(() => window.clearTimeout(limiteSalas));

        try {
            const data = validarEquipos(await apiGetDatos(PCS_URL, { cache: 'no-store', signal: equiposController.signal }));
            if (!vigente()) return;
            beforeCardsChange();
            setEquipos(data);
            consultaExitosa.current = true;
            setUltimaConsulta(new Date().toISOString());
            setEstado('ok');
        } catch (error) {
            if (vigente()) setEstado(error.estado === 403 ? 'denegado' : 'error');
        } finally {
            window.clearTimeout(limiteEquipos);
            await consultarSalas;
            if (vigente()) {
                request.current = null;
                setCargando(false);
            }
        }
    }, [beforeCardsChange]);

    useEffect(() => {
        let timer;
        let visible = true;
        let generacion = 0;
        const cargarSiVisible = () => {
            if (visible && !document.hidden && !pausa.current) return cargar({ automatica: true });
        };
        function programar() {
            const ciclo = generacion;
            timer = window.setTimeout(async () => {
                await cargarSiVisible();
                if (visible && ciclo === generacion) programar();
            }, 15000);
        }
        function salir() {
            visible = false;
            generacion++;
            window.clearTimeout(timer);
            const consulta = request.current;
            request.current = null;
            consulta?.cancelar();
        }
        function volver(event) {
            if (!event.persisted) return;
            visible = true;
            setCargando(false);
            cargarSiVisible();
            programar();
        }

        cargar();
        programar();
        document.addEventListener('visibilitychange', cargarSiVisible);
        window.addEventListener('pagehide', salir);
        window.addEventListener('pageshow', volver);
        return () => {
            salir();
            document.removeEventListener('visibilitychange', cargarSiVisible);
            window.removeEventListener('pagehide', salir);
            window.removeEventListener('pageshow', volver);
        };
    }, [cargar]);

    function actualizarPrueba(agentId, check) {
        setEquipos(current => current.map(pc => pc.agent_id === agentId ? { ...pc, smile_check: check } : pc));
    }

    function actualizarNombre(agentId, name) {
        setEquipos(current => current.map(pc => pc.agent_id === agentId ? { ...pc, name } : pc));
    }

    return { equipos, salas, salasConsultadas, errorSalas, ultimaConsulta, estado, cargando, cargar, actualizarPrueba, actualizarNombre };
}

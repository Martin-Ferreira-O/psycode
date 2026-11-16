import { useCallback, useEffect, useReducer, useState } from "react";
import { apiGetDatos, ErrorSolicitud } from "../api.js";

export function useResource(load) {
    const [request, requestLoad] = useReducer((_, keepDataFor) => ({ keepDataFor }), null);
    const [response, setResponse] = useState(null);
    const reload = useCallback(() => requestLoad(null), []);
    const refresh = useCallback(() => requestLoad(load), [load]);
    const keepData = request?.keepDataFor === load;

    useEffect(() => {
        const controller = new AbortController();
        async function fetchData() {
            try {
                const data = await load(controller.signal);
                if (!controller.signal.aborted) {
                    setResponse({ load, request, data, lastSuccess: data });
                }
            } catch (error) {
                if (!controller.signal.aborted) {
                    setResponse(previous => ({
                        load, request, error, lastSuccess: previous?.lastSuccess,
                        data: keepData && previous?.load === load ? previous.data : undefined,
                    }));
                }
            }
        }
        void fetchData();
        return () => controller.abort();
    }, [load, request, keepData]);

    const current = response?.load === load && response.request === request
        ? response
        : null;
    const retainedData = keepData && response?.load === load ? response.data : undefined;
    return {
        loading: current === null && retainedData === undefined,
        refreshing: current === null && retainedData !== undefined,
        data: retainedData ?? current?.data,
        previousData: response?.lastSuccess,
        error: retainedData === undefined ? current?.error : undefined,
        refreshError: retainedData === undefined ? undefined : current?.error,
        reload,
        refresh,
    };
}

export function usePage(url, query, offset, limit) {
    const load = useCallback(async (signal) => {
        const params = new URLSearchParams(query);
        params.set("limit", String(limit));
        let pageOffset = offset;
        while (!signal.aborted) {
            params.set("offset", String(pageOffset));
            const data = await apiGetDatos(`${url}?${params}`, { cache: "no-store", signal });
            if (!Array.isArray(data?.items) || !Number.isInteger(data.total) || data.total < 0) {
                throw new ErrorSolicitud();
            }
            if (data.total === 0 || pageOffset < data.total) {
                return { ...data, offset: data.total === 0 ? 0 : pageOffset };
            }
            pageOffset = Math.floor((data.total - 1) / limit) * limit;
        }
    }, [url, query, offset, limit]);
    return useResource(load);
}

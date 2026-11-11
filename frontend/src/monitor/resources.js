import { useCallback, useEffect, useReducer, useState } from "react";
import { apiGetDatos, ErrorSolicitud } from "../api.js";

export function useResource(load) {
    const [revision, reload] = useReducer((value) => value + 1, 0);
    const [response, setResponse] = useState(null);

    useEffect(() => {
        const controller = new AbortController();
        async function fetchData() {
            try {
                const data = await load(controller.signal);
                if (!controller.signal.aborted) {
                    setResponse({ load, revision, data, lastSuccess: data });
                }
            } catch (error) {
                if (!controller.signal.aborted) {
                    setResponse((previous) => ({ load, revision, error, lastSuccess: previous?.lastSuccess }));
                }
            }
        }
        void fetchData();
        return () => controller.abort();
    }, [load, revision]);

    const current = response?.load === load && response.revision === revision
        ? response
        : null;
    return {
        loading: current === null,
        data: current?.data,
        previousData: response?.lastSuccess,
        error: current?.error,
        reload,
    };
}

export function usePage(url, query, offset, limit) {
    const load = useCallback(async (signal) => {
        const params = new URLSearchParams(query);
        params.set("limit", String(limit));
        let pageOffset = offset;
        while (!signal.aborted) {
            params.set("offset", String(pageOffset));
            const data = await apiGetDatos(`${url}?${params}`, { signal });
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

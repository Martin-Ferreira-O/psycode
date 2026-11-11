import { useRef, useState } from "react";
import { apiGet, ErrorSolicitud } from "../api.js";
import { Button, Icon, Status } from "../ui.jsx";

export default function ExcelDownload({ id, url, fallbackFilename }) {
    const downloading = useRef(false);
    const [busy, setBusy] = useState(false);
    const [feedback, setFeedback] = useState(null);

    async function download() {
        if (downloading.current || !url) return;
        downloading.current = true;
        setBusy(true);
        setFeedback(null);
        try {
            const response = await apiGet(url);
            if (!response) return;
            if (response.status === 204) {
                setFeedback({ type: "vacio", text: "No hay registros para exportar con los filtros seleccionados." });
                return;
            }
            if (!response.ok) throw new ErrorSolicitud(response.status);

            const objectUrl = URL.createObjectURL(await response.blob());
            const filename = response.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1];
            const link = document.createElement("a");
            link.href = objectUrl;
            link.download = filename || fallbackFilename;
            document.body.append(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
        } catch {
            setFeedback({ type: "error", text: "No fue posible generar el archivo Excel." });
        } finally {
            downloading.current = false;
            setBusy(false);
        }
    }

    return (
        <>
            <Button id={id} variant="success" busy={busy} busyLabel="Descargando…" disabled={!url} onClick={download}>
                <Icon name="download" />
                Descargar Excel
            </Button>
            {feedback && <Status type={feedback.type}>{feedback.text}</Status>}
        </>
    );
}

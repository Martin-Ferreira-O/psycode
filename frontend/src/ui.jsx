import { useLayoutEffect, useRef, useState } from "react";
import { describirError } from "./api.js";

export function Button({
    variant = "secondary", className = "", iconOnly = false, busy = false,
    busyLabel = "Cargando…", type = "button", disabled, href, children, ...props
}) {
    const classes = ["ui-button", className].filter(Boolean).join(" ");
    const attributes = {
        ...props,
        className: classes,
        "data-variant": variant,
        "data-icon-only": iconOnly || undefined,
        "aria-busy": busy || undefined,
    };
    const content = busy ? <><span className="ui-spinner" aria-hidden="true" />{!iconOnly && busyLabel}</> : children;

    if (href && !(busy || disabled)) return <a {...attributes} href={href}>{content}</a>;
    return <button {...attributes} type={type} disabled={disabled || busy}>{content}</button>;
}

export function Badge({ tone = "neutral", className = "", children, ...props }) {
    return <span {...props} className={`ui-badge ${className}`} data-tone={tone}>{children}</span>;
}

export function FilterSelect({ label, value, onChange, children }) {
    return (
        <div className="ui-filter-select">
            <Icon name="filter" className="ui-filter-icon" />
            <select className="ui-button" aria-label={label} value={value}
                data-filtered={Boolean(value)} onChange={event => onChange(event.target.value)}>
                {children}
            </select>
            <Icon name="chevron_down" className="ui-filter-chevron" />
        </div>
    );
}

export function DataTable({ label, className = "", wrapperClassName = "", wrapperId, stickyActions, children, ...props }) {
    const region = useRef(null);
    const table = useRef(null);
    const [overflowing, setOverflowing] = useState(false);

    useLayoutEffect(() => {
        const container = region.current;
        const measure = () => setOverflowing(container.scrollWidth > container.clientWidth);
        const observer = new ResizeObserver(measure);
        observer.observe(container);
        observer.observe(table.current);
        measure();
        return () => observer.disconnect();
    }, []);

    return (
        <div ref={region} id={wrapperId} className={`ui-table-scroll ${wrapperClassName}`}
            role="region" aria-label={label} tabIndex={overflowing ? 0 : undefined}
            data-sticky-actions={stickyActions && overflowing || undefined}>
            {overflowing && <p className="ui-table-hint"><Icon name="arrow_forward" /> Desplaza para ver más columnas</p>}
            <table {...props} ref={table} className={`ui-table ${className}`}>
                {children}
            </table>
        </div>
    );
}

export function Skeleton({ className = "" } = {}) {
    return <span className={`ui-skeleton ${className}`} aria-hidden="true" />;
}

export function SkeletonRows({ columns, rows = 4 }) {
    return Array.from({ length: rows }, (_, row) => (
        <tr key={row} aria-hidden="true">
            {Array.from({ length: columns }, (_, column) => (
                <td key={column}><Skeleton /></td>
            ))}
        </tr>
    ));
}

export function Status({ type = "carga", children, error, messages, onRetry, className = "", ...props }) {
    const [retrying, setRetrying] = useState(false);
    const [retryError, setRetryError] = useState(null);
    const activeError = retryError ?? error;
    const description = activeError ? describirError(activeError, messages) : null;
    if (description?.omitido) return null;

    async function retry() {
        setRetrying(true);
        try {
            await onRetry();
            setRetryError(null);
        } catch (error) {
            if (!describirError(error).omitido) setRetryError(error);
        } finally {
            setRetrying(false);
        }
    }

    return (
        <div {...props} className={`estado-solicitud ${className}`} data-estado={type}
            role={type === "error" ? "alert" : "status"} aria-atomic="true">
            {retryError ? description.mensaje : children ?? description?.mensaje}
            {onRetry && (!description || description.recuperable) && (
                <Button className="boton-reintentar" busy={retrying} onClick={retry}>Reintentar</Button>
            )}
        </div>
    );
}

const focusable = "a[href], button, input, select, textarea, summary, [tabindex]";

function wrapDialogFocus(event) {
    if (event.key !== "Tab") return;
    const dialog = event.currentTarget;
    const backwards = event.shiftKey;
    const controls = [...dialog.querySelectorAll(focusable)].filter(control =>
        control.tabIndex >= 0 && !control.matches(":disabled") &&
        control.getClientRects().length > 0 && getComputedStyle(control).visibility === "visible"
    );
    if (backwards) controls.reverse();

    // Native radio groups have one Tab stop and retain arrow-key navigation.
    const stops = controls.filter(control => {
        if (!control.matches("input[type=radio][name]")) return true;
        const group = controls.filter(radio =>
            radio.type === "radio" && radio.name === control.name && radio.form === control.form
        );
        return control === (group.find(radio => radio.checked) ?? group[0]);
    });

    if (!controls.includes(document.activeElement) || document.activeElement === stops.at(-1)) {
        event.preventDefault();
        (stops[0] ?? dialog).focus();
    }
}

export function Dialog({ open, onClose, title, className = "", children, busy = false,
    initialFocusRef, returnFocusRef, ref, ...props }) {
    const element = useRef(null);
    const backdropPress = useRef(false);

    useLayoutEffect(() => {
        if (!open) return;
        const dialog = element.current;
        const previous = document.activeElement;
        if (!dialog.open) dialog.showModal();
        initialFocusRef?.current?.focus();

        return () => {
            dialog.close();
            const target = returnFocusRef?.current || previous;
            if (target?.isConnected) target.focus({ preventScroll: true });
        };
    }, [open, initialFocusRef, returnFocusRef]);

    function outside(event) {
        if (event.target !== element.current) return false;
        const { top, bottom, left, right } = element.current.getBoundingClientRect();
        return event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom;
    }

    return (
        <dialog aria-busy={busy || undefined} {...props}
            ref={node => {
                element.current = node;
                if (typeof ref === "function") ref(node);
                else if (ref) ref.current = node;
            }}
            className={`ui-dialog ${className}`} aria-label={title} tabIndex={-1}
            onKeyDown={wrapDialogFocus}
            onCancel={event => {
                event.preventDefault();
                if (!busy) onClose?.();
            }}
            onPointerDown={event => { backdropPress.current = outside(event); }}
            onClick={event => {
                if (!busy && backdropPress.current && outside(event)) onClose?.();
                backdropPress.current = false;
            }}>
            {children}
        </dialog>
    );
}

const iconPaths = {
    arrow_back: "M19 12H5m7-7-7 7 7 7",
    arrow_forward: "M5 12h14m-7-7 7 7-7 7",
    bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9m-8 12a2 2 0 0 0 4 0",
    calendar: "M3 5h18v16H3zm0 5h18M8 3v4m8-4v4m-8 7h2m4 0h2m-8 3h2",
    chevron_down: "m6 9 6 6 6-6",
    chevron_left: "m15 18-6-6 6-6",
    chevron_right: "m9 18 6-6-6-6",
    check: "m5 12 4 4L19 6",
    close: "m6 6 12 12M18 6 6 18",
    content_copy: "M8 8h12v12H8zM16 4H4v12",
    dashboard: "M3 3h7v9H3zm11 0h7v5h-7zM3 16h7v5H3zm11-4h7v9h-7z",
    download: "M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4",
    edit: "M4 20h4L20 8l-4-4L4 16zm10-14 4 4",
    email: "M3 5h18v14H3zm0 2 9 6 9-6",
    fact_check: "M4 4h16v16H4zm3 8 2 2 4-4m2 1h2m-2 4h2",
    history: "M4 11a8 8 0 1 1 1 5m-1-5V5m0 6h6m2-4v5l3 2",
    hard_drive: "M5 5h14l3 9v5H2v-5zm-3 9h20M6 17h.1m4 0h.1",
    filter: "M3 4h18l-7 8v6l-4 2v-8Z",
    info: "M12 11v5m0-8v.1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z",
    lock: "M5 10h14v11H5zm3 0V7a4 4 0 0 1 8 0v3",
    lock_open: "M5 10h14v11H5zm3 0V7a4 4 0 0 1 7.5-2",
    logout: "M10 4H4v16h6m4-12 4 4-4 4m-6-4h10",
    manage_accounts: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m11-13a4 4 0 1 1-8 0 4 4 0 0 1 8 0Zm6 0v8m-4-4h8",
    menu: "M4 6h16M4 12h16M4 18h16",
    microphone: "M9 6a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0zM5 11v1a7 7 0 0 0 14 0v-1m-7 8v3m-3 0h6",
    monitor: "M3 4h18v12H3zm9 12v4m-5 0h10",
    person: "M20 21a8 8 0 0 0-16 0m12-14a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
    add: "M12 5v14M5 12h14",
    refresh: "M20 7v5h-5m5 0a8 8 0 1 0-2 6",
    remove: "M5 12h14",
    search: "M15 15l5 5m-3-10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z",
    settings: "M4 7h16M4 17h16M8 4v6m8 4v6",
    visibility: "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
    visibility_off: "m3 3 18 18M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 5.3A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17.8 17.8 0 0 1-2.1 3M6.2 6.2C3.5 8 2 12 2 12s3.5 7 10 7a9.6 9.6 0 0 0 4.2-.9",
    view_grid: "M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z",
    view_table: "M3 5h18v14H3zm0 5h18M3 14h18M9 5v14",
    warning: "M12 3 2 20h20zm0 6v4m0 3v.1",
};

export function Icon({ name, className = "", ...props }) {
    return <svg {...props} className={`ui-icon ${className}`} viewBox="0 0 24 24" aria-hidden="true">
        <path d={iconPaths[name]} />
    </svg>;
}

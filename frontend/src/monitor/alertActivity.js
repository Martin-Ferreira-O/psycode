import { apiGetDatos, ErrorSolicitud } from "../api.js";
import { ALERTS_URL, getAlertCount } from "./alerts.js";

const santiagoClock = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Santiago",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
});

// UTC dates here are calendar labels for Santiago, not instants used as API bounds.
const calendarFormatter = (options) => new Intl.DateTimeFormat("es-CL", { ...options, timeZone: "UTC" });
const fullDay = calendarFormatter({ weekday: "long", day: "numeric", month: "long" });
const shortDay = calendarFormatter({ day: "numeric", month: "short" });
const shortDayWithYear = calendarFormatter({ day: "numeric", month: "short", year: "numeric" });
const weekday = calendarFormatter({ weekday: "short" });
const shortMonth = calendarFormatter({ month: "short" });
const fullMonth = calendarFormatter({ month: "long", year: "numeric" });

function santiagoParts(instant) {
    return Object.fromEntries(santiagoClock.formatToParts(instant).map(({ type, value }) => [type, value]));
}

function dateKey(date) {
    return date.toISOString().slice(0, 10);
}

function startCase(label) {
    return label.charAt(0).toUpperCase() + label.slice(1);
}

export async function loadRecentActivity(signal) {
    const { year, month, day } = santiagoParts(new Date());
    const dates = Array.from({ length: 7 }, (_, index) => new Date(Date.UTC(+year, month - 1, day - (6 - index))));
    const firstDay = dates[0];
    const today = dates.at(-1);
    const todayKey = dateKey(today);
    const countsByDay = new Map(dates.map(date => [dateKey(date), 0]));
    const countsByHour = Array.from({ length: 24 }, () => 0);
    const seen = new Set();
    const params = new URLSearchParams({ fecha_desde: dateKey(firstDay), fecha_hasta: todayKey, limit: "100" });

    for (let offset = 0; !signal.aborted;) {
        params.set("offset", String(offset));
        const data = await apiGetDatos(`${ALERTS_URL}?${params}`, { cache: "no-store", signal });
        if (!Array.isArray(data?.items) || !Number.isInteger(data.total) || data.total < 0) {
            throw new ErrorSolicitud();
        }

        for (const { alerta_id, fecha_hora } of data.items) {
            // New alerts can shift items onto the next page while it is loading.
            if (seen.has(alerta_id)) continue;
            seen.add(alerta_id);
            const instant = Date.parse(fecha_hora);
            if (!Number.isFinite(instant)) throw new ErrorSolicitud();
            const local = santiagoParts(instant);
            const key = `${local.year}-${local.month}-${local.day}`;
            if (!countsByDay.has(key)) continue;
            countsByDay.set(key, countsByDay.get(key) + 1);
            if (key === todayKey) countsByHour[Number(local.hour)]++;
        }

        offset += data.items.length;
        if (offset >= data.total) break;
        if (data.items.length === 0) throw new ErrorSolicitud();
    }

    const weekRange = firstDay.getUTCFullYear() === today.getUTCFullYear() ? shortDay : shortDayWithYear;
    return {
        daily: {
            range: `Hoy · ${fullDay.format(today)}`,
            buckets: countsByHour.map((total, hour) => {
                const label = `${String(hour).padStart(2, "0")}:00`;
                return { label, name: label, total };
            }),
        },
        weekly: {
            range: weekRange.formatRange(firstDay, today),
            buckets: dates.map(date => ({
                label: startCase(weekday.format(date).replace(".", "")),
                name: startCase(fullDay.format(date)),
                total: countsByDay.get(dateKey(date)),
            })),
        },
    };
}

export async function loadMonthlyActivity(signal) {
    const { year, month } = santiagoParts(new Date());
    const months = Array.from({ length: 6 }, (_, index) => new Date(Date.UTC(+year, month - 6 + index, 1)));
    const buckets = await Promise.all(months.map(async (start) => {
        const end = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0));
        const total = await getAlertCount({ fecha_desde: dateKey(start), fecha_hasta: dateKey(end) }, signal);
        return {
            label: startCase(shortMonth.format(start).replace(".", "")),
            name: startCase(fullMonth.format(start)),
            total,
        };
    }));

    return { range: startCase(fullMonth.formatRange(months[0], months.at(-1))), buckets };
}

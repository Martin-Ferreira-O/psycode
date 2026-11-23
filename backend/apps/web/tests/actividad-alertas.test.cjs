const { test } = require('node:test');
const assert = require('node:assert/strict');

test('la actividad agrupa las horas de Santiago y no cuenta alertas repetidas entre páginas', async (t) => {
    const { loadRecentActivity } = await import('../../../../frontend/src/monitor/alertActivity.js');
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-04-05T03:30:00Z') });
    globalThis.document = { cookie: '' };
    t.after(() => { delete globalThis.document; });

    const previousDay = Array.from({ length: 98 }, (_, index) => ({
        alerta_id: `anterior-${index}`,
        fecha_hora: '2026-04-03T18:00:00Z',
    }));
    const today = [
        { alerta_id: 'hoy-3', fecha_hora: '2026-04-05T03:05:00Z' },
        { alerta_id: 'hoy-2', fecha_hora: '2026-04-05T02:05:00Z' },
        { alerta_id: 'hoy-1', fecha_hora: '2026-04-05T01:55:00Z' },
    ];
    const requests = [];
    t.mock.method(globalThis, 'fetch', async (url) => {
        const params = new URL(url, 'https://example.test').searchParams;
        assert.equal(params.get('fecha_desde'), '2026-03-29');
        assert.equal(params.get('fecha_hasta'), '2026-04-04');
        assert.equal(params.get('limit'), '100');
        const offset = Number(params.get('offset'));
        requests.push(offset);
        const items = offset === 0 ? [...today, ...previousDay.slice(0, 97)] : previousDay.slice(-2);
        return Response.json({ success: true, data: { items, total: offset === 0 ? 101 : 102 } });
    });

    const { daily, weekly } = await loadRecentActivity(new AbortController().signal);

    assert.deepEqual(requests, [0, 100]);
    assert.equal(daily.buckets.length, 24);
    assert.deepEqual(daily.buckets.map(bucket => bucket.total), [...Array(22).fill(0), 1, 2]);
    assert.deepEqual(weekly.buckets.map(bucket => bucket.total), [0, 0, 0, 0, 0, 98, 3]);
});

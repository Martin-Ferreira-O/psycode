'use client';

import React, { useState } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { ArrowLeft, Download, AlertTriangle, BarChart2 } from 'lucide-react';

interface AlertaHistorica {
  id: string;
  tipo: 'Riesgo suicida' | 'Vulneración de derechos';
  fecha: string;
  hora: string;
  estado: 'Pendiente' | 'Revisada';
}

const datosSemana = [
  { name: 'Lun', total: 3 },
  { name: 'Mar', total: 5 },
  { name: 'Mié', total: 4 },
  { name: 'Jue', total: 7 },
  { name: 'Vie', total: 5 },
  { name: 'Sáb', total: 2 },
  { name: 'Dom', total: 1 },
];

const datosMes = [
  { name: 'Sem 1', total: 15 },
  { name: 'Sem 2', total: 22 },
  { name: 'Sem 3', total: 18 },
  { name: 'Sem 4', total: 27 },
];

const registrosMock: AlertaHistorica[] = [
  {
    id: 'ALT-2026-084',
    tipo: 'Riesgo suicida',
    fecha: '08 sep 2026',
    hora: '14:37',
    estado: 'Pendiente',
  },
  {
    id: 'ALT-2026-083',
    tipo: 'Vulneración de derechos',
    fecha: '08 sep 2026',
    hora: '13:12',
    estado: 'Pendiente',
  },
  {
    id: 'ALT-2026-082',
    tipo: 'Riesgo suicida',
    fecha: '08 sep 2026',
    hora: '11:48',
    estado: 'Revisada',
  },
  {
    id: 'ALT-2026-081',
    tipo: 'Vulneración de derechos',
    fecha: '08 sep 2026',
    hora: '10:25',
    estado: 'Revisada',
  },
];

export default function PaginaEstadisticas() {
  const [periodo, setPeriodo] = useState<'semana' | 'mes'>('semana');
  const datosGrafico = periodo === 'semana' ? datosSemana : datosMes;

  return (
    <div className="min-h-screen bg-slate-50 p-6 md:p-10 font-sans">
      <div className="max-w-7xl mx-auto">
        {/* Botón Volver */}
        <button
          onClick={() => alert('Navegar de regreso al Dashboard')}
          className="flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-slate-800 transition-colors mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          Regresar al Dashboard
        </button>

        {/* Encabezado y selector de período */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <span className="text-xs font-bold uppercase tracking-wider text-blue-600">
              Resumen Estadístico
            </span>
            <h1 className="text-2xl font-bold text-slate-900 mt-1">
              Alertas de hoy
            </h1>
          </div>

          <div className="inline-flex bg-slate-200/80 p-1 rounded-full w-fit">
            <button
              onClick={() => setPeriodo('semana')}
              className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-all ${
                periodo === 'semana'
                  ? 'bg-slate-900 text-white shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Semana
            </button>
            <button
              onClick={() => setPeriodo('mes')}
              className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-all ${
                periodo === 'mes'
                  ? 'bg-slate-900 text-white shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Mes
            </button>
          </div>
        </div>

        {/* Cuadrícula principal */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Tarjeta del Gráfico */}
          <div className="lg:col-span-7 bg-white rounded-2xl border border-slate-200/80 p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-base font-bold text-slate-900">
                  {periodo === 'semana'
                    ? 'Comportamiento semanal'
                    : 'Comportamiento mensual'}
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Cantidad de alertas registradas por período
                </p>
              </div>
              <div className="p-2 bg-slate-100 rounded-lg text-slate-600">
                <BarChart2 className="w-5 h-5" />
              </div>
            </div>

            <div className="h-[280px] w-full pt-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={datosGrafico}
                  margin={{ top: 20, right: 10, left: -25, bottom: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    vertical={false}
                    stroke="#f1f5f9"
                  />
                  <XAxis
                    dataKey="name"
                    tickLine={false}
                    axisLine={{ stroke: '#e2e8f0' }}
                    tick={{ fill: '#64748b', fontSize: 12 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: '#64748b', fontSize: 12 }}
                    allowDecimals={false}
                  />
                  <Tooltip
                    cursor={{ fill: '#f8fafc' }}
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        return (
                          <div className="bg-slate-900 text-white text-xs px-3 py-1.5 rounded-md shadow-lg font-medium">
                            {`${payload[0].payload.name}: ${payload[0].value} alertas`}
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Bar
                    dataKey="total"
                    fill="#2b5278"
                    radius={[6, 6, 0, 0]}
                    label={{
                      position: 'top',
                      fill: '#1e293b',
                      fontSize: 12,
                      fontWeight: 600,
                    }}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Tarjeta del Registro Histórico */}
          <div className="lg:col-span-5 bg-white rounded-2xl border border-slate-200/80 p-6 shadow-sm">
            <h2 className="text-base font-bold text-slate-900">
              Registro histórico
            </h2>
            <p className="text-xs text-slate-500 mt-0.5 mb-4">
              Últimos movimientos del período seleccionado
            </p>

            <button className="w-full flex items-center justify-center gap-2 bg-[#12284b] hover:bg-[#1a3663] text-white text-xs font-semibold py-2.5 px-4 rounded-xl transition-colors mb-5 shadow-sm">
              <Download className="w-3.5 h-3.5" />
              Obtener registro de {periodo === 'semana' ? 'semana' : 'mes'}
            </button>

            <div className="space-y-3">
              {registrosMock.map((alerta) => (
                <div
                  key={alerta.id}
                  className="flex items-center justify-between p-3.5 rounded-xl border border-slate-100 bg-slate-50/50 hover:bg-slate-50 transition-colors"
                >
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-lg bg-blue-50 text-blue-600 mt-0.5">
                      <AlertTriangle className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="text-xs font-bold text-slate-900 block">
                        {alerta.id}
                      </span>
                      <span className="text-xs font-medium text-slate-600 block mt-0.5">
                        {alerta.tipo}
                      </span>
                      <span className="text-[11px] text-slate-400 block mt-0.5">
                        {alerta.fecha} · {alerta.hora}
                      </span>
                    </div>
                  </div>

                  <span
                    className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border ${
                      alerta.estado === 'Pendiente'
                        ? 'bg-amber-50 text-amber-700 border-amber-200'
                        : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    }`}
                  >
                    {alerta.estado}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
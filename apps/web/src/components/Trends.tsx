'use client'

import { useEffect, useState } from 'react'
import { api, fmtDate } from '../lib/api'

const W = 520, H = 200, PAD = { left: 44, right: 16, top: 14, bottom: 26 }
const LINE = '#1d4ed8'

/** One small chart per lab: line + points, shaded reference band, hover tooltip, table view. */
export default function Trends({ patientId, onSelectFact }: { patientId: string; onSelectFact: (id: string) => void }) {
  const [data, setData] = useState<any | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api(`/patients/${patientId}/trends`).then(setData).catch(e => setError(e.message))
  }, [patientId])

  if (error) return <p role="alert" className="text-red-700">{error}</p>
  if (!data) return <p className="text-slate-500">Loading trends…</p>
  if (!data.series.length) return <p className="text-slate-500">No verified lab or vital results yet. Upload a lab report to see trends.</p>
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      {data.series.map((series: any) => <TrendChart key={series.loinc} series={series} onSelectFact={onSelectFact} />)}
    </div>
  )
}

function TrendChart({ series, onSelectFact }: { series: any; onSelectFact: (id: string) => void }) {
  const [hover, setHover] = useState<number | null>(null)
  const [table, setTable] = useState(false)
  const points = series.points.map((p: any) => ({ ...p, t: new Date(p.at).getTime() }))
  const { low, high } = series.range
  const values = [...points.map((p: any) => p.value), ...(low != null ? [low] : []), ...(high != null ? [high] : [])]
  const span = Math.max(...values) - Math.min(...values) || 1
  const yMin = Math.min(...values) - span * 0.15, yMax = Math.max(...values) + span * 0.15
  const tMin = points[0].t, tMax = points[points.length - 1].t
  const x = (t: number) => tMax === tMin ? (PAD.left + W - PAD.right) / 2 : PAD.left + ((t - tMin) / (tMax - tMin)) * (W - PAD.left - PAD.right)
  const y = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom)
  const outside = (v: number) => (low != null && v < low) || (high != null && v > high)
  const ticks = [yMin + (yMax - yMin) * 0.1, (yMin + yMax) / 2, yMax - (yMax - yMin) * 0.1]
  const active = hover != null ? points[hover] : null

  return (
    <section className="bg-white border border-slate-200 p-4">
      <header className="flex justify-between items-baseline mb-1">
        <h3 className="font-semibold">{series.name} <span className="text-slate-500 font-normal text-sm">({series.unit})</span></h3>
        <button onClick={() => setTable(!table)} className="text-xs text-blue-700 hover:underline">{table ? 'Show chart' : 'Show table'}</button>
      </header>
      <p className="text-sm text-slate-700 mb-2">{series.summary}</p>

      {table ? (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-slate-500"><th className="py-1">Date</th><th>Value</th><th>In range</th><th /></tr></thead>
          <tbody>
            {points.map((p: any) => (
              <tr key={p.fact_id} className="border-t border-slate-100">
                <td className="py-1">{fmtDate(p.at)}</td><td className="font-mono">{p.value} {series.unit}</td>
                <td>{outside(p.value) ? 'outside' : 'inside'}</td>
                <td className="text-right"><button onClick={() => onSelectFact(p.fact_id)} className="text-blue-700 hover:underline">source →</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={series.summary} onMouseLeave={() => setHover(null)}>
            {low != null && high != null && (
              <>
                <rect x={PAD.left} y={y(high)} width={W - PAD.left - PAD.right} height={y(low) - y(high)} fill="#15803d" opacity={0.1} />
                <text x={W - PAD.right - 4} y={y(high) + 12} textAnchor="end" fontSize="10" fill="#64748b">reference range {low}–{high}</text>
              </>
            )}
            {ticks.map(tick => (
              <g key={tick}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} stroke="#e2e8f0" strokeWidth={1} />
                <text x={PAD.left - 6} y={y(tick) + 3} textAnchor="end" fontSize="10" fill="#64748b">{tick.toFixed(1)}</text>
              </g>
            ))}
            {active && <line x1={x(active.t)} x2={x(active.t)} y1={PAD.top} y2={H - PAD.bottom} stroke="#94a3b8" strokeWidth={1} />}
            <polyline points={points.map((p: any) => `${x(p.t)},${y(p.value)}`).join(' ')} fill="none" stroke={LINE} strokeWidth={2} strokeLinejoin="round" />
            {points.map((p: any, i: number) => (
              <g key={p.fact_id}>
                {/* out-of-range points are hollow, so the flag does not depend on colour */}
                <circle cx={x(p.t)} cy={y(p.value)} r={5} fill={outside(p.value) ? '#ffffff' : LINE} stroke={outside(p.value) ? LINE : '#ffffff'} strokeWidth={2} />
                <circle cx={x(p.t)} cy={y(p.value)} r={16} fill="transparent" className="cursor-pointer"
                  onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onClick={() => onSelectFact(p.fact_id)}
                  tabIndex={0} role="button" aria-label={`${series.name} ${p.value} ${series.unit} on ${fmtDate(p.at)}. Open source.`} />
              </g>
            ))}
            <text x={PAD.left} y={H - 8} fontSize="10" fill="#64748b">{fmtDate(points[0].at)}</text>
            {points.length > 1 && <text x={W - PAD.right} y={H - 8} textAnchor="end" fontSize="10" fill="#64748b">{fmtDate(points[points.length - 1].at)}</text>}
          </svg>
          {active && (
            <div className="absolute pointer-events-none bg-slate-900 text-white text-xs px-2 py-1 -translate-x-1/2"
              style={{ left: `${(x(active.t) / W) * 100}%`, top: 0 }}>
              <span className="font-mono font-semibold">{active.value} {series.unit}</span> · {fmtDate(active.at)}
              {outside(active.value) && ' · outside range'} · click for source
            </div>
          )}
          <p className="text-xs text-slate-500 mt-1">● inside reference range &nbsp; ○ outside reference range</p>
        </div>
      )}
    </section>
  )
}

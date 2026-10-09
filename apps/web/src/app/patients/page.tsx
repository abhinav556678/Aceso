'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { api, fmtDate, getRole } from '../../lib/api'

export default function PatientsList() {
  const [data, setData] = useState<any | null>(null)
  const [error, setError] = useState('')
  const role = getRole()

  useEffect(() => {
    api('/patients').then(setData).catch(e => setError(e.message))
  }, [])

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-5xl mx-auto">
        <header className="mb-6 flex justify-between items-center">
          <h1 className="text-2xl font-bold">Patients</h1>
          <nav className="flex gap-4 text-sm">
            {role === 'admin' && <Link href="/admin" className="text-blue-700 hover:underline">Audit log</Link>}
            <Link href="/" className="text-blue-700 hover:underline">Switch role ({role || 'none'})</Link>
          </nav>
        </header>

        {error && <p role="alert" className="mb-4 border border-red-300 bg-red-50 text-red-800 rounded p-3">{error}</p>}
        {!data && !error && <p className="text-slate-500">Loading patients…</p>}

        {data?.overdue_loops.length > 0 && (
          <section className="mb-6 bg-white border border-amber-300 rounded-lg p-4">
            <h2 className="font-semibold mb-2">⏳ Overdue follow-ups ({data.overdue_loops.length})</h2>
            <ul className="space-y-1 text-sm">
              {data.overdue_loops.map((loop: any) => (
                <li key={loop.id}>
                  <Link href={`/patients/${loop.patient_id}`} className="text-blue-700 hover:underline">{loop.patient_name}</Link>
                  {' — '}{loop.description} <span className="text-slate-500">(due {fmtDate(loop.due_date)})</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {data && (
          <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-100 text-slate-700">
                <tr>
                  <th className="p-3">MRN</th><th className="p-3">Name</th><th className="p-3">Age / Sex</th>
                  {role !== 'admin' && <th className="p-3">Needs attention</th>}
                  <th className="p-3" />
                </tr>
              </thead>
              <tbody>
                {data.patients.map((p: any) => (
                  <tr key={p.id} className="border-t border-slate-100">
                    <td className="p-3 font-mono">{p.mrn}</td>
                    <td className="p-3 font-medium">{p.full_name}</td>
                    <td className="p-3">{p.age} {p.sex}</td>
                    {role !== 'admin' && (
                      <td className="p-3 space-x-2">
                        {p.open_alerts > 0 && <span className="text-[var(--sev-critical)] font-semibold">⛔ {p.open_alerts} open alert{p.open_alerts > 1 ? 's' : ''}</span>}
                        {p.unverified > 0 && <span className="text-[var(--state-extracted)]">◔ {p.unverified} unverified</span>}
                        {p.overdue_loops > 0 && <span className="text-slate-600">⏳ {p.overdue_loops} overdue</span>}
                        {!p.open_alerts && !p.unverified && !p.overdue_loops && <span className="text-slate-400">—</span>}
                      </td>
                    )}
                    <td className="p-3 text-right">
                      {role !== 'admin'
                        ? <Link href={`/patients/${p.id}`} className="text-blue-700 font-medium hover:underline">Open chart →</Link>
                        : <span className="text-slate-400 text-xs">demographics only</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  )
}

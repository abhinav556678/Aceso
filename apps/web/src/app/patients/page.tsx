'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import TopBar from '../../components/TopBar'
import { api, fmtDate, getRole, Role } from '../../lib/api'

export default function PatientsList() {
  const [data, setData] = useState<any | null>(null)
  const [error, setError] = useState('')
  // the role lives in localStorage, so it is only known after the page loads in the browser
  const [role, setRole] = useState<Role | null>(null)

  useEffect(() => {
    setRole(getRole())
    api('/patients').then(setData).catch(e => setError(e.message))
  }, [])

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar />
      <main className="p-8">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-2xl font-semibold mb-6">Patients</h1>

        {error && <p role="alert" className="card border-l-4 mb-4 px-4 py-3" style={{ borderLeftColor: 'var(--sev-critical)' }}>{error}</p>}
        {!data && !error && <p className="text-slate-500">Loading patients…</p>}

        {data?.overdue_loops.length > 0 && (
          <section className="card border-l-4 mb-6 px-6 py-4" style={{ borderLeftColor: 'var(--state-extracted)' }}>
            <h2 className="label mb-2">Overdue follow-ups · {data.overdue_loops.length}</h2>
            <ul className="space-y-1 text-sm">
              {data.overdue_loops.map((loop: any) => (
                <li key={loop.id}>
                  <Link href={`/patients/${loop.patient_id}`} className="link">{loop.patient_name}</Link>
                  {' — '}{loop.description} <span className="text-slate-500">(due {fmtDate(loop.due_date)})</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {data && (
          <div className="card overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="label border-b border-slate-200" style={{ background: 'var(--bg)' }}>
                <tr>
                  <th className="px-5 py-3.5">MRN</th><th className="px-5 py-3.5">Name</th><th className="px-5 py-3.5">Age / Sex</th>
                  {role !== 'admin' && <th className="px-5 py-3.5">Needs attention</th>}
                  <th className="px-5 py-3.5" />
                </tr>
              </thead>
              <tbody>
                {data.patients.map((p: any) => (
                  <tr key={p.id} className="border-t border-slate-100">
                    <td className="px-5 py-3.5 font-mono">{p.mrn}</td>
                    <td className="px-5 py-3.5 font-medium">{p.full_name}</td>
                    <td className="px-5 py-3.5">{p.age} {p.sex}</td>
                    {role !== 'admin' && (
                      <td className="px-5 py-3.5 space-x-2">
                        {p.open_alerts > 0 && <span className="text-[var(--sev-critical)] font-semibold">{p.open_alerts} open alert{p.open_alerts > 1 ? 's' : ''}</span>}
                        {p.unverified > 0 && <span className="text-[var(--state-extracted)]">{p.unverified} unverified</span>}
                        {p.overdue_loops > 0 && <span className="text-slate-600">{p.overdue_loops} overdue</span>}
                        {!p.open_alerts && !p.unverified && !p.overdue_loops && <span className="text-slate-400">—</span>}
                      </td>
                    )}
                    <td className="px-5 py-3.5 text-right">
                      {role !== 'admin'
                        ? <Link href={`/patients/${p.id}`} className="link font-medium">Open chart</Link>
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
    </div>
  )
}

'use client'

import { useEffect, useState } from 'react'
import PrivacyReceipt, { RedactionTryout } from '../../components/PrivacyReceipt'
import TopBar from '../../components/TopBar'
import { api, post } from '../../lib/api'

export default function AuditLog() {
  const [data, setData] = useState<any | null>(null)
  const [status, setStatus] = useState<any | null>(null)
  const [chain, setChain] = useState<any | null>(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  const [receiptJob, setReceiptJob] = useState<string | null>(null)

  useEffect(() => {
    api('/admin/audit').then(setData).catch(e => setError(e.message))
    api('/status').then(setStatus).catch(() => {})
  }, [])

  const rows = data?.rows.filter((r: any) => !filter || `${r.action} ${r.actor_label} ${r.mrn}`.toLowerCase().includes(filter.toLowerCase())) || []

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar />
      <main className="p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-2xl font-semibold mb-6">Audit log</h1>

        {error && <p role="alert" className="mb-4 border border-red-300 bg-red-50 text-red-800 p-3">{error}</p>}
        {status && (
          <p className="mb-4 bg-white border border-slate-200 p-3 text-sm">
            Model layer: <b>{status.llm_mode === 'onprem' ? 'on-premises' : 'external API'}</b> · extraction {status.llm}
            {status.stt && <> · speech-to-text {status.stt}</>}. Text is redacted before it leaves; each call is logged below as <code>llm.call</code> with
            the SHA-256 of what was sent, and the row opens the message itself. Audio is sent for transcription as recorded.
          </p>
        )}

        <RedactionTryout />

        <div className="flex flex-wrap gap-3 items-center mb-4">
          <button onClick={() => post('/admin/audit/verify').then(setChain).catch(e => setError(e.message))}
            className="bg-slate-800 text-white px-4 py-2 text-sm font-medium">Verify hash chain</button>
          {chain && (chain.ok
            ? <span className="text-green-800 font-semibold">✓ Chain intact — no row has been altered or removed</span>
            : <span className="text-red-700 font-semibold">✕ Chain broken at row {chain.broken_at}</span>)}
          <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter by action, actor or MRN"
            aria-label="Filter audit rows" className="ml-auto border border-slate-300 px-3 py-2 text-sm bg-white w-64" />
        </div>

        {!data && !error && <p className="text-slate-500">Loading…</p>}
        {data && (
          <>
            <p className="text-sm text-slate-500 mb-2">Showing {rows.length} of {data.total} rows, newest first. The table is append-only at the database level.</p>
            <div className="bg-white border border-slate-200 overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-100 text-slate-700">
                  <tr><th className="p-2">#</th><th className="p-2">Time</th><th className="p-2">Actor</th><th className="p-2">Action</th><th className="p-2">Patient</th><th className="p-2">Change</th><th className="p-2">Details</th></tr>
                </thead>
                <tbody>
                  {rows.map((row: any) => (
                    <tr key={row.id} className="border-t border-slate-100 align-top">
                      <td className="p-2 font-mono text-slate-500">{row.id}</td>
                      <td className="p-2 whitespace-nowrap">{new Date(row.at).toLocaleString('en-GB')}</td>
                      <td className="p-2">{row.actor_label}{row.actor_role && <span className="text-slate-500"> ({row.actor_role})</span>}</td>
                      <td className="p-2 font-mono">{row.action}</td>
                      <td className="p-2 font-mono">{row.mrn || '—'}</td>
                      <td className="p-2 whitespace-nowrap">{row.to_state ? `${row.from_state || '∅'} → ${row.to_state}` : '—'}</td>
                      <td className="p-2 text-slate-600 font-mono text-xs break-all">
                        {JSON.stringify(row.payload)}
                        {row.action === 'llm.call' && row.payload?.sent_sha256 && (
                          <button onClick={() => setReceiptJob(row.entity_id)} className="block font-sans text-sm text-blue-700 hover:underline mt-1">See what was sent →</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
      </main>
      {receiptJob && <PrivacyReceipt key={receiptJob} jobId={receiptJob} onClose={() => setReceiptJob(null)} />}
    </div>
  )
}

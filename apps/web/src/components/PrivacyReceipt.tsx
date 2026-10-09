'use client'

import { useEffect, useState } from 'react'
import { api, post } from '../lib/api'

type Span = [number, number, string]

const LABELS: Record<string, [string, string]> = {
  PERSON: ['name', 'names'], MRN: ['MRN', 'MRNs'], PHONE: ['phone number', 'phone numbers'], EMAIL: ['email', 'emails'],
  ABHA: ['ABHA number', 'ABHA numbers'], AADHAAR: ['Aadhaar number', 'Aadhaar numbers'],
  DOB: ['date of birth', 'dates of birth'], ADDRESS: ['address', 'addresses'],
}

const tally = (counts: Record<string, number> = {}) =>
  Object.entries(counts).map(([label, n]) => `${n} ${(LABELS[label] || [label, label])[n > 1 ? 1 : 0]}`).join(', ')

/** Text as it left the machine: each placeholder shown as a solid chip. */
function Sent({ text }: { text: string }) {
  return <>{text.split(/(<[A-Z]+>)/).map((part, index) => /^<[A-Z]+>$/.test(part)
    ? <span key={index} className="font-mono text-xs bg-slate-800 text-white px-1 py-0.5 mx-0.5">{part}</span>
    : part)}</>
}

/** The original text with every removed part marked. */
function Original({ text, spans }: { text: string; spans: Span[] }) {
  const parts: React.ReactNode[] = []
  let cursor = 0
  spans.forEach(([start, end, label], index) => {
    parts.push(text.slice(cursor, start))
    parts.push(<mark key={index} title={`Removed: ${LABELS[label]?.[0] || label}`} className="bg-red-100 text-red-900 line-through decoration-red-700 px-0.5">{text.slice(start, end)}</mark>)
    cursor = end
  })
  return <>{parts}{text.slice(cursor)}</>
}

function destination(model: string): string {
  if (model.startsWith('scripted:')) return 'Demo seed data: a scripted stand-in answered this call, so nothing was sent anywhere. This is what a model would have received.'
  if (model.startsWith('onprem:')) return `Handled by the on-premises model ${model.slice(7)}. Nothing left this machine.`
  return `Sent to the external model ${model.replace('external:', '')}.`
}

/** "What the model saw": the exact prompt that left the machine, next to what was removed from it. */
export default function PrivacyReceipt({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const [data, setData] = useState<any | null>(null)
  const [error, setError] = useState('')

  useEffect(() => { api(`/jobs/${jobId}/privacy`).then(setData).catch(e => setError(e.message)) }, [jobId])

  return (
    <div className="fixed inset-0 bg-slate-900/40 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="What the model saw">
      <div className="w-full max-w-4xl bg-white h-full flex flex-col">
        <header className="p-5 border-b border-slate-200 flex justify-between items-start gap-4">
          <div>
            <p className="text-sm font-bold uppercase tracking-wide text-slate-500">Privacy receipt</p>
            <h2 className="text-lg font-semibold mt-1">What the model saw{data?.filename ? ` · ${data.filename}` : ''}</h2>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-slate-500 hover:text-slate-900 text-2xl leading-none">×</button>
        </header>

        <div className="p-5 overflow-y-auto flex-1 text-sm space-y-5">
          {error && <p role="alert" className="border border-red-300 bg-red-50 text-red-800 p-3">{error}</p>}
          {!data && !error && <p className="text-slate-500">Loading…</p>}
          {data?.audio_sent_unredacted && (
            <p className="bg-amber-50 border border-amber-300 p-3">
              The audio of this recording was sent to {data.stt_model} for transcription as recorded. Speech cannot be redacted;
              only the transcript below is redacted before fact extraction.
            </p>
          )}
          {data && !data.calls.length && <p className="text-slate-600">No language-model call is recorded for this upload.</p>}
          {data && !data.shows_original && data.calls.length > 0 && (
            <p className="bg-slate-100 border border-slate-300 p-3">An admin audits what left the machine. The original text is shown to clinical roles only.</p>
          )}

          {data?.calls.map((call: any) => (
            <section key={call.seq}>
              <p className="font-medium">{destination(call.model)}</p>
              <p className="text-slate-600 mt-1">
                {new Date(call.created_at).toLocaleString('en-GB')} · {call.units.length} line(s) of evidence ·{' '}
                {Object.keys(call.redacted || {}).length ? <>removed first: <b>{tally(call.redacted)}</b></> : 'no identifiers found to remove'}
              </p>
              {call.error && <p className="text-amber-800 mt-1">The call failed after this was sent: {call.error}</p>}
              <p className="mt-1 font-mono text-xs break-all">
                {call.intact
                  ? <span className="text-green-800">✓ sha256 {call.sha256} — matches audit row #{data.audit_id}</span>
                  : <span className="text-red-700">✕ sha256 {call.sha256} — does not match the audit log; this record was changed after the call</span>}
              </p>

              <div className="mt-3 border border-slate-200 overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-slate-100 text-slate-700 text-xs uppercase tracking-wide">
                    <tr>
                      <th className="p-2 w-12">Line</th>
                      {data.shows_original && <th className="p-2 w-1/2">Stays on this machine</th>}
                      <th className="p-2">Sent to the model</th>
                    </tr>
                  </thead>
                  <tbody>
                    {call.units.map((unit: any) => (
                      <tr key={unit.unit} className={`border-t border-slate-100 align-top ${unit.sent.includes('<') ? 'bg-yellow-50' : ''}`}>
                        <td className="p-2 font-mono text-xs text-slate-500">{unit.unit}</td>
                        {data.shows_original && <td className="p-2">{unit.original != null ? <Original text={unit.original} spans={unit.spans} /> : <span className="text-slate-400">source removed</span>}</td>}
                        <td className="p-2"><Sent text={unit.sent} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <details className="mt-3">
                <summary className="cursor-pointer text-slate-600">The complete message, exactly as handed to the model adapter</summary>
                <pre className="mt-2 bg-slate-100 border border-slate-200 p-3 text-xs whitespace-pre-wrap break-words">{call.system_prompt}{'\n\n'}{call.user_message}</pre>
              </details>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

/** Type any text and see what the redactor would let through. Nothing is stored or sent. */
export function RedactionTryout() {
  const [text, setText] = useState('Patient Name: Asha Verma, DOB: 12/03/1976, phone 9876543210. Seen by Dr. Iyer. Creatinine 2.1 mg/dL. Continue Glycomet 500 BD.')
  const [name, setName] = useState('')
  const [result, setResult] = useState<any | null>(null)
  const [error, setError] = useState('')

  const run = () => post('/privacy/preview', { text, patient_name: name }).then(r => { setResult(r); setError('') }).catch(e => setError(e.message))

  return (
    <section className="mb-6 bg-white border border-slate-200 p-4 text-sm">
      <h2 className="font-semibold">Try the redactor</h2>
      <p className="text-slate-600 mb-3">The same code that runs before every model call. Type anything; it is not stored and not sent anywhere.</p>
      <textarea value={text} onChange={e => setText(e.target.value)} rows={3} maxLength={5000} aria-label="Text to redact"
        className="w-full border border-slate-300 px-3 py-2 font-mono text-xs" />
      <div className="flex flex-wrap gap-3 items-center mt-2">
        <input value={name} onChange={e => setName(e.target.value)} placeholder="Registered patient name (optional)" aria-label="Registered patient name"
          className="border border-slate-300 px-3 py-2 w-72" />
        <button onClick={run} className="bg-slate-800 text-white px-4 py-2 font-medium">Show what would be sent</button>
      </div>
      {error && <p role="alert" className="text-red-700 mt-2">{error}</p>}
      {result && (
        <div className="mt-3 grid md:grid-cols-2 gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-1">Stays on this machine</p>
            <p className="border border-slate-200 p-3"><Original text={text} spans={result.spans} /></p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-1">Would be sent · {tally(result.redacted) || 'nothing'} removed</p>
            <p className="border border-slate-200 p-3"><Sent text={result.sent} /></p>
          </div>
        </div>
      )}
    </section>
  )
}

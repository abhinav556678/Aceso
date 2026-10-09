'use client'

import { useState } from 'react'
import { post } from '../lib/api'

export const SEVERITY: Record<string, { icon: string; label: string; color: string }> = {
  critical: { icon: '■', label: 'Critical', color: 'var(--sev-critical)' },
  high: { icon: '▲', label: 'High', color: 'var(--sev-high)' },
  moderate: { icon: '◆', label: 'Moderate', color: 'var(--sev-moderate)' },
  info: { icon: '○', label: 'Info', color: 'var(--sev-info)' },
}

/** The "Explain" drawer: the rule, every input it used, and where each input came from. */
export default function AlertDrawer({ alert, facts, canAct, onClose, onChanged, onSelectFact }: {
  alert: any; facts: any[]; canAct: boolean; onClose: () => void; onChanged: () => void; onSelectFact: (id: string) => void
}) {
  const [reason, setReason] = useState('')
  const [keep, setKeep] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const severity = SEVERITY[alert.severity] || SEVERITY.info
  const isContradiction = alert.rule_id === 'RECORD-CONTRADICTION'
  const trace = alert.trace
  const reasonOk = reason.trim().length >= 10

  const act = async (action: string, body: object) => {
    setBusy(true)
    setError('')
    try {
      await post(`/alerts/${alert.id}/${action}`, body)
      onChanged()
      onClose()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const factLink = (id?: string) => id && (
    <button onClick={() => { onSelectFact(id); onClose() }} className="ml-2 text-blue-700 hover:underline text-xs whitespace-nowrap">view source →</button>
  )

  return (
    <div className="fixed inset-0 bg-slate-900/40 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Alert explanation">
      <div className="w-full max-w-xl bg-white h-full flex flex-col">
        <header className="p-5 border-b border-slate-200 flex justify-between items-start gap-4">
          <div>
            <p className="text-sm font-bold uppercase tracking-wide" style={{ color: severity.color }}>{severity.icon} {severity.label} · {alert.status}</p>
            <h2 className="text-lg font-semibold mt-1">{alert.message}</h2>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-slate-500 hover:text-slate-900 text-2xl leading-none">×</button>
        </header>

        <div className="p-5 overflow-y-auto flex-1 text-sm">
          <h3 className="font-semibold text-slate-500 uppercase tracking-wide text-xs mb-1">Rule</h3>
          <p className="font-mono bg-slate-100 border border-slate-200 px-3 py-2">{trace.rule?.id} · v{trace.rule?.version}</p>
          <p className="text-slate-600 mt-1 mb-5">Source: {trace.rule?.source}</p>

          <h3 className="font-semibold text-slate-500 uppercase tracking-wide text-xs mb-2">How the engine got here</h3>
          <ol className="border-l-2 border-slate-200 ml-2 space-y-4">
            {trace.steps.map((step: any, index: number) => (
              <li key={index} className="pl-4 relative">
                <span className="absolute -left-[9px] top-0.5 w-4 h-4 bg-white border-2 border-slate-400" aria-hidden />
                <p className="font-medium">
                  {step.label}
                  {step.value !== undefined && <span className="font-mono"> = {step.value} {step.unit}</span>}
                  {step.result !== undefined && <span className="ml-2 font-mono text-xs px-1.5 py-0.5 bg-slate-100 border border-slate-300">{step.result ? '✓ TRUE' : '✕ FALSE'}</span>}
                  {factLink(step.fact_id)}
                </p>
                {step.formula && <p className="text-slate-600">Formula: {step.formula} (computed in code)</p>}
                {step.evidence && <p className="text-slate-600">{step.evidence}</p>}
                {step.inputs && (
                  <ul className="mt-1 space-y-0.5 text-slate-700">
                    {step.inputs.map((input: any) => (
                      <li key={input.name}>└ {input.name}: <span className="font-mono">{input.value} {input.unit}</span>
                        {input.source && <span className="text-slate-500"> · {input.source}</span>}{factLink(input.fact_id)}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
          <p className="mt-5 font-semibold border-t border-slate-200 pt-4">⇒ {trace.conclusion}</p>
          {alert.override_reason && <p className="mt-3 text-slate-600">Recorded reason: “{alert.override_reason}”</p>}
        </div>

        {alert.status === 'open' && (
          <footer className="p-5 border-t border-slate-200 bg-slate-50 space-y-3">
            {!canAct ? (
              <p className="text-sm text-slate-600">Only a doctor can acknowledge, override or resolve an alert.</p>
            ) : (
              <>
                {isContradiction && (
                  <fieldset className="text-sm space-y-1">
                    <legend className="font-semibold mb-1">Which statement is true? The other will be superseded.</legend>
                    {alert.trigger_fact_ids.map((id: string) => {
                      const fact = facts.find(f => f.id === id)
                      return (
                        <label key={id} className="flex gap-2 items-start">
                          <input type="radio" name="keep" checked={keep === id} onChange={() => setKeep(id)} className="mt-1" />
                          <span>{fact ? `${fact.assertion === 'denied' ? 'Denied' : 'Present'}: ${fact.display} — “${fact.raw_text}”` : id}</span>
                        </label>
                      )
                    })}
                  </fieldset>
                )}
                <label className="block text-sm font-semibold" htmlFor="reason">Reason (written to the audit log, min. 10 characters)</label>
                <textarea id="reason" value={reason} onChange={e => setReason(e.target.value)} rows={2}
                  className="w-full border border-slate-300 p-2 text-sm bg-white" />
                {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
                <div className="flex gap-3">
                  {isContradiction ? (
                    <button disabled={busy || !reasonOk || !keep} onClick={() => act('resolve', { keep_fact_id: keep, reason })}
                      className="flex-1 bg-blue-600 text-white font-semibold py-2 disabled:opacity-40">Resolve contradiction</button>
                  ) : (
                    <>
                      <button disabled={busy || !reasonOk} onClick={() => act('acknowledge', { reason })}
                        className="flex-1 bg-blue-600 text-white font-semibold py-2 disabled:opacity-40">Acknowledge</button>
                      <button disabled={busy || !reasonOk} onClick={() => act('override', { reason })}
                        className="flex-1 bg-white border border-slate-400 font-semibold py-2 disabled:opacity-40">Override…</button>
                    </>
                  )}
                </div>
              </>
            )}
          </footer>
        )}
      </div>
    </div>
  )
}

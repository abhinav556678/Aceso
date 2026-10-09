'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import AlertDrawer, { SEVERITY } from '../../../components/AlertDrawer'
import ConsultRecorder from '../../../components/ConsultRecorder'
import PrivacyReceipt from '../../../components/PrivacyReceipt'
import SourceViewer, { ScanReview } from '../../../components/SourceViewer'
import Trends from '../../../components/Trends'
import { api, ApiError, fileUrl, fmtDate, getRole, post, REASONS } from '../../../lib/api'

type Tab = 'review' | 'timeline' | 'trends' | 'search'

const STATE: Record<string, { icon: string; label: string; color: string }> = {
  extracted: { icon: '◔', label: 'Unverified', color: 'var(--state-extracted)' },
  verified: { icon: '✓', label: 'Verified', color: 'var(--state-verified)' },
  clinician_confirmed: { icon: '✓✓', label: 'Doctor-confirmed', color: 'var(--state-confirmed)' },
  rejected: { icon: '✕', label: 'Rejected', color: 'var(--state-rejected)' },
}
const LANG: Record<string, string> = { en: 'English', ta: 'தமிழ்', hi: 'हिन्दी' }

function factValue(fact: any): string {
  const dose = fact.dose || {}
  if (fact.fact_type === 'medication' && dose.amount != null) return `${dose.amount} ${dose.unit || 'mg'}${dose.freq ? ' ' + dose.freq : ''}`
  if (fact.fact_type === 'medication' && dose.freq) return dose.freq
  if (fact.value_num != null) return `${fact.value_num} ${fact.unit || ''}`
  return ''
}

// the patient id is only known at request time, so the chart streams in behind Suspense
export default function PatientChartPage() {
  return <Suspense fallback={<main className="p-8 text-slate-500">Loading chart…</main>}><PatientChart /></Suspense>
}

function PatientChart() {
  const { id } = useParams<{ id: string }>()
  const role = getRole()
  const isDoctor = role === 'doctor'
  const [chart, setChart] = useState<any | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [tab, setTab] = useState<Tab>('review')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [openAlertId, setOpenAlertId] = useState<string | null>(null)
  const [blockers, setBlockers] = useState<string[]>([])
  const [receiptJob, setReceiptJob] = useState<string | null>(null)
  const [scanDoc, setScanDoc] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await api(`/patients/${id}/chart`)
      setChart(data)
      setError('')
      if (data.encounter) {
        const check = await api(`/encounters/${data.encounter.id}/sign-check`)
        setBlockers(check.blockers)
      }
    } catch (e: any) {
      setError(e.message)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  // while a pipeline job is running, poll so facts and alerts appear as they land
  const running = chart?.jobs.some((j: any) => j.status === 'queued' || j.status === 'running')
  useEffect(() => {
    if (!running) return
    const timer = setInterval(load, 1500)
    return () => clearInterval(timer)
  }, [running, load])

  const selectFact = (factId: string) => { setSelectedId(factId); setTab('review') }

  const run = async (action: () => Promise<any>, done?: string) => {
    setNotice('')
    try {
      await action()
      if (done) setNotice(done)
      await load()
    } catch (e: any) {
      setError(e instanceof ApiError && e.blockers.length ? `${e.message} ${e.blockers.join('; ')}.` : e.message)
    }
  }

  const upload = (file?: File) => {
    if (!file) return
    const form = new FormData()
    form.append('patient_id', id)
    form.append('file', file)
    run(() => api('/ingest', { method: 'POST', body: form }))
  }

  const derived = useMemo(() => {
    if (!chart) return null
    const facts: any[] = chart.facts
    const openAlerts = chart.alerts.filter((a: any) => a.status === 'open')
    const flagged = new Set<string>(openAlerts.flatMap((a: any) => a.trigger_fact_ids))
    return {
      openAlerts,
      handledAlerts: chart.alerts.filter((a: any) => a.status !== 'open'),
      flagged,
      attention: facts.filter(f => f.state === 'extracted' || (f.current_encounter && f.state === 'verified' && !f.collapsible)),
      collapsed: facts.filter(f => f.current_encounter && f.state === 'verified' && f.collapsible),
      record: facts.filter(f => f.state === 'clinician_confirmed'),
      rejected: facts.filter(f => f.state === 'rejected'),
      selected: facts.find(f => f.id === selectedId) || null,
    }
  }, [chart, selectedId])

  if (error && !chart) {
    return <main className="p-8"><p role="alert" className="border border-red-300 bg-red-50 text-red-800 p-3 max-w-xl">{error}</p>
      <Link href="/patients" className="text-blue-700 hover:underline mt-4 inline-block">← Patients</Link></main>
  }
  if (!chart || !derived) return <main className="p-8 text-slate-500">Loading chart…</main>

  const { patient, encounter, note } = chart
  const signed = encounter?.status === 'signed'
  const openAlert = chart.alerts.find((a: any) => a.id === openAlertId)

  const factCard = (fact: any) => {
    const state = STATE[fact.state] || STATE.extracted
    const denied = fact.assertion === 'denied'
    const reviewable = fact.state === 'extracted' || fact.state === 'verified'
    return (
      <div
        key={fact.id}
        onClick={() => setSelectedId(fact.id)}
        className={` border bg-white p-3 cursor-pointer ${selectedId === fact.id ? 'border-blue-600' : 'border-slate-200 hover:border-slate-400'}`}
      >
        <div className="flex justify-between items-start gap-2">
          <p className={`font-semibold ${fact.state === 'rejected' ? 'line-through text-slate-500' : ''}`}>
            {denied && <span className="text-slate-600 font-normal">Denied: </span>}
            {fact.assertion === 'uncertain' && <span className="text-slate-600 font-normal">Uncertain: </span>}
            {fact.display} <span className="font-mono font-normal">{factValue(fact)}</span>
          </p>
          <span className="text-xs whitespace-nowrap font-semibold" style={{ color: state.color }}>{state.icon} {state.label}</span>
        </div>
        <p className="text-xs text-slate-500 mt-0.5">
          {fact.fact_type.replace('_', ' ')} · {fact.source === 'document' ? `${fact.document_name || 'document'} p.${fact.page_no}` : fact.source === 'audio' ? 'consult' : 'computed'}
          {' · '}{fmtDate(fact.effective_at)}{fact.confidence != null && fact.source !== 'manual' ? ` · confidence ${Math.round(fact.confidence * 100)}%` : ''}
        </p>
        {fact.raw_text && fact.source !== 'manual' && <p className="text-sm text-slate-700 mt-1">“{fact.raw_text}”</p>}
        {fact.attention_reasons?.map((reason: string) => (
          <p key={reason} className="text-sm mt-1" style={{ color: 'var(--state-extracted)' }}>◔ {REASONS[reason] || reason}</p>
        ))}
        {derived.flagged.has(fact.id) && <p className="text-sm mt-1 font-semibold" style={{ color: 'var(--sev-critical)' }}>Involved in an open safety alert</p>}
        {reviewable && !signed && (
          <div className="flex gap-2 mt-2" onClick={e => e.stopPropagation()}>
            {isDoctor && <button onClick={() => run(() => post(`/facts/${fact.id}/confirm`))} className="text-sm bg-green-700 text-white px-3 py-1 hover:bg-green-800">Confirm</button>}
            <button onClick={() => run(() => post(`/facts/${fact.id}/reject`))} className="text-sm border border-slate-400 px-3 py-1 hover:bg-slate-100">Reject</button>
          </div>
        )}
      </div>
    )
  }

  const noteSection = (title: string, items: any[]) => (
    <section className="mb-5" key={title}>
      <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wide border-b border-slate-200 pb-1 mb-2">{title}</h3>
      {!items?.length ? <p className="text-sm text-slate-400 italic">Nothing verified yet</p> : (
        <ul className="space-y-1">
          {items.map((item, index) => {
            const factId = item.fact_ids[0]
            return (
              <li key={index}>
                <button onClick={() => setSelectedId(factId)}
                  className={`text-left text-sm px-1 hover:bg-yellow-100 ${selectedId === factId ? 'bg-yellow-200' : ''}`}>
                  {item.text}
                  {derived.flagged.has(factId) && <span className="ml-2 font-semibold" style={{ color: 'var(--sev-critical)' }}>alert</span>}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-bold">{patient.full_name} · {patient.age} {patient.sex} · MRN {patient.mrn} · {LANG[patient.preferred_lang] || patient.preferred_lang}</h1>
          <p className="text-sm text-slate-500">
            {encounter ? `${encounter.chief_complaint || 'Visit'} · ${fmtDate(encounter.started_at)} · ${signed ? 'signed' : 'in progress'}` : 'No visit yet'}
            {' · '}signed in as {chart.viewer.name} ({chart.viewer.role})
          </p>
        </div>
        <Link href="/patients" className="text-blue-700 hover:underline text-sm">← Patients</Link>
      </header>

      {/* safety banner: always visible on every tab */}
      <div className="px-6 pt-3 space-y-2">
        {error && <p role="alert" className="border border-red-300 bg-red-50 text-red-800 p-3 text-sm flex justify-between"><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss">×</button></p>}
        {notice && <p role="status" className="border border-green-300 bg-green-50 text-green-900 p-3 text-sm">{notice}</p>}
        {derived.openAlerts.map((alert: any) => {
          const severity = SEVERITY[alert.severity] || SEVERITY.info
          return (
            <div key={alert.id} className="bg-white border-l-8 border p-3 flex justify-between items-center gap-4" style={{ borderColor: severity.color }}>
              <p><span className="font-bold uppercase text-sm" style={{ color: severity.color }}>{severity.icon} {severity.label}</span> · <span className="font-medium">{alert.message}</span></p>
              <button onClick={() => setOpenAlertId(alert.id)} className="shrink-0 border border-slate-400 px-3 py-1 text-sm font-semibold hover:bg-slate-100">Explain &amp; act</button>
            </div>
          )
        })}
        {chart.unverified_count > 0 && (
          <p className="bg-amber-50 border border-amber-300 p-3 text-sm">
            ◔ {chart.unverified_count} fact{chart.unverified_count > 1 ? 's are' : ' is'} not yet verified and {chart.unverified_count > 1 ? 'were' : 'was'} not evaluated by the safety engine. No alert does not mean safe.
          </p>
        )}
        {chart.safety_notes.map((n: any) => <p key={n.rule_id} className="bg-slate-100 border border-slate-300 p-3 text-sm">{n.message} ({n.rule_id} not evaluated)</p>)}
        {derived.handledAlerts.length > 0 && (
          <details className="text-sm text-slate-600">
            <summary className="cursor-pointer">{derived.handledAlerts.length} handled alert(s)</summary>
            <ul className="mt-1 space-y-1">
              {derived.handledAlerts.map((a: any) => (
                <li key={a.id}><button onClick={() => setOpenAlertId(a.id)} className="hover:underline text-left">{a.status}: {a.message}</button></li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <nav className="px-6 mt-3 flex gap-6 text-sm font-medium border-b border-slate-200" aria-label="Chart sections">
        {(['review', 'timeline', 'trends', 'search'] as Tab[]).map(name => (
          <button key={name} onClick={() => setTab(name)} aria-current={tab === name}
            className={`py-2 border-b-2 capitalize ${tab === name ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>
            {name === 'review' ? 'Review & note' : name}
          </button>
        ))}
      </nav>

      {tab === 'review' && (
        <div className="flex-1 grid lg:grid-cols-3 gap-0 min-h-0">
          {/* facts */}
          <section className="border-r border-slate-200 p-5 space-y-5 overflow-y-auto">
            <div>
              <div className="flex flex-wrap items-start gap-2">
                <label className={`inline-block bg-blue-600 text-white font-medium py-2 px-4 text-sm ${signed ? 'opacity-40' : 'cursor-pointer hover:bg-blue-700'}`}>
                  Upload PDF, scan or photo, audio or transcript
                  <input type="file" className="hidden" accept=".pdf,.txt,image/*,audio/*" disabled={signed}
                    onChange={e => { upload(e.target.files?.[0]); e.target.value = '' }} />
                </label>
                <ConsultRecorder disabled={signed} onRecorded={upload} />
              </div>
              <p className="text-xs text-slate-500 mt-1">A recording is sent to the transcription service as recorded; only its transcript is redacted.</p>
              <ul className="mt-2 space-y-1">
                {chart.jobs.map((job: any) => (
                  <li key={job.id} className="text-sm border border-slate-200 bg-white px-3 py-2">
                    <span className="font-medium">{job.filename}</span>{' — '}
                    {job.status === 'failed' ? <span className="text-red-700">✕ Failed: {job.error}</span>
                      : job.status === 'done' ? <span className="text-green-800">✓ {job.result?.facts} facts ({job.result?.verified} verified, {job.result?.needs_attention} need attention, {job.result?.possible_omissions} possible omissions)</span>
                        : <span className="text-blue-700 animate-pulse">{job.stage}…</span>}
                    {job.result?.warning && <span className="block text-amber-800">{job.result.warning}</span>}
                    {job.result?.ocr && (
                      <span className="block text-slate-600">
                        Scan read by OCR on this machine · {job.result.ocr.rows} row(s)
                        {job.result.ocr.unreadable + job.result.ocr.low_confidence > 0 && (
                          <button onClick={() => setScanDoc(job.result.document_id)} className="ml-1 font-semibold hover:underline" style={{ color: 'var(--state-extracted)' }}>
                            ◔ {job.result.ocr.unreadable + job.result.ocr.low_confidence} could not be read reliably — show on page →
                          </button>
                        )}
                      </span>
                    )}
                    {job.result?.llm_calls > 0 && (
                      <button onClick={() => setReceiptJob(job.id)} className="block text-blue-700 hover:underline text-left">
                        {job.result.redacted} identifier{job.result.redacted === 1 ? '' : 's'} removed before the model call — see what the model saw →
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <h2 className="text-sm font-bold uppercase tracking-wide mb-2" style={{ color: 'var(--state-extracted)' }}>Needs your attention ({derived.attention.length})</h2>
              <p className="text-xs text-slate-500 mb-2">Unverified facts, plus every allergy and medication from this visit — these are never auto-collapsed.</p>
              <div className="space-y-2">
                {derived.attention.map(factCard)}
                {!derived.attention.length && <p className="text-sm text-slate-500">Nothing waiting for review.</p>}
              </div>
            </div>

            <details>
              <summary className="cursor-pointer text-sm font-semibold" style={{ color: 'var(--state-verified)' }}>✓ {derived.collapsed.length} verified item(s) hidden — labs, vitals, history</summary>
              <div className="space-y-2 mt-2">{derived.collapsed.map(factCard)}</div>
            </details>
            <details>
              <summary className="cursor-pointer text-sm font-semibold" style={{ color: 'var(--state-confirmed)' }}>✓✓ {derived.record.length} doctor-confirmed fact(s) on record</summary>
              <div className="space-y-2 mt-2">{derived.record.map(factCard)}</div>
            </details>
            {derived.rejected.length > 0 && (
              <details>
                <summary className="cursor-pointer text-sm font-semibold text-slate-500">✕ {derived.rejected.length} rejected</summary>
                <div className="space-y-2 mt-2">{derived.rejected.map(factCard)}</div>
              </details>
            )}

            <div>
              <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500 mb-2">This consult</h2>
              <ul className="text-sm space-y-1">
                {chart.gaps.map((gap: any) => (
                  <li key={gap.key}>
                    {gap.status === 'captured' ? '✓' : gap.status === 'missing' ? '○' : '•'} {gap.label}
                    {gap.status === 'missing' && <span className="text-slate-500"> — not captured yet</span>}
                    {gap.detail && <span className="text-slate-600"> — {gap.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          </section>

          {/* note + sign-off */}
          <section className="border-r border-slate-200 p-5 bg-white overflow-y-auto">
            <div className="flex justify-between items-baseline mb-3">
              <h2 className="text-lg font-semibold">SOAP note</h2>
              <span className="text-xs text-slate-500">{note ? `${note.status} · ${note.generated_by}` : ''}</span>
            </div>
            {!note ? <p className="text-sm text-slate-500">No draft yet. Upload a document or a consult recording to start.</p> : (
              <>
                <p className="text-xs text-slate-500 mb-3">Built only from verified facts. Click any sentence to see its source.</p>
                {noteSection('Subjective', note.subjective)}
                {noteSection('Objective', note.objective)}
                {noteSection('Assessment', note.assessment)}
                {noteSection('Plan', note.plan)}
              </>
            )}

            {encounter && (
              <div className="mt-6 border-t border-slate-200 pt-4">
                {signed ? (
                  <>
                    <p className="font-semibold text-green-800 mb-1">Signed {fmtDate(note?.signed_at)} — the note is locked</p>
                    {note?.content_hash && <p className="text-xs font-mono text-slate-500 break-all mb-3">sha256 {note.content_hash}</p>}
                    <div className="flex flex-wrap gap-2">
                      <a target="_blank" rel="noreferrer" href={fileUrl(`/encounters/${encounter.id}/fhir`)} className="border border-slate-400 px-3 py-1.5 text-sm hover:bg-slate-100">FHIR bundle</a>
                      {Object.entries(LANG).map(([code, name]) => (
                        <a key={code} target="_blank" rel="noreferrer" href={fileUrl(`/encounters/${encounter.id}/patient-summary?lang=${code}`)}
                          className="border border-slate-400 px-3 py-1.5 text-sm hover:bg-slate-100">Patient summary · {name}</a>
                      ))}
                    </div>
                  </>
                ) : (
                  <>
                    <h3 className="font-semibold mb-2">Sign-off</h3>
                    {blockers.length > 0 ? (
                      <ul className="text-sm space-y-1 mb-3">{blockers.map(b => <li key={b}>○ {b}</li>)}</ul>
                    ) : <p className="text-sm text-green-800 mb-3">✓ Everything is reviewed. Ready to sign.</p>}
                    <button disabled={!isDoctor || blockers.length > 0}
                      onClick={() => run(() => post(`/encounters/${encounter.id}/sign`), 'Encounter signed. Facts confirmed, note locked, audit log written.')}
                      className="bg-green-700 text-white font-semibold py-2 px-4 disabled:opacity-40 hover:bg-green-800">
                      Sign off &amp; finalise
                    </button>
                    {!isDoctor && <p className="text-xs text-slate-500 mt-2">Only a doctor can sign.</p>}
                  </>
                )}
              </div>
            )}
          </section>

          {/* provenance */}
          <section className="p-5 bg-slate-100 overflow-y-auto">
            {scanDoc && <ScanReview key={scanDoc} documentId={scanDoc} onClose={() => setScanDoc(null)} />}
            <SourceViewer fact={derived.selected} onSelectFact={selectFact} />
          </section>
        </div>
      )}

      {tab === 'timeline' && <Timeline patientId={id} onSelectFact={selectFact} />}
      {tab === 'trends' && <div className="p-6"><Trends patientId={id} onSelectFact={selectFact} /></div>}
      {tab === 'search' && <Search patientId={id} onSelectFact={selectFact} />}

      {openAlert && (
        <AlertDrawer alert={openAlert} facts={chart.facts} canAct={isDoctor} onClose={() => setOpenAlertId(null)}
          onChanged={load} onSelectFact={selectFact} />
      )}
      {receiptJob && <PrivacyReceipt key={receiptJob} jobId={receiptJob} onClose={() => setReceiptJob(null)} />}
    </div>
  )
}

const KIND_LABEL: Record<string, string> = { encounter: 'Visit', document: 'Document', alert: 'Alert' }

function Timeline({ patientId, onSelectFact }: { patientId: string; onSelectFact: (id: string) => void }) {
  const [events, setEvents] = useState<any[] | null>(null)
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState('')
  useEffect(() => { api(`/patients/${patientId}/timeline`).then(d => setEvents(d.events)).catch(e => setError(e.message)) }, [patientId])
  if (error) return <p role="alert" className="p-6 text-red-700">{error}</p>
  if (!events) return <p className="p-6 text-slate-500">Loading timeline…</p>

  const group = (kind: string) => kind.startsWith('fact:') ? ({ 'fact:lab_result': 'labs', 'fact:vital': 'labs', 'fact:medication': 'meds', 'fact:diagnosis': 'diagnoses' } as any)[kind] || 'other' : kind + 's'
  const filters = ['all', 'encounters', 'labs', 'meds', 'diagnoses', 'alerts', 'documents']
  const shown = events.filter(e => filter === 'all' || group(e.kind) === filter)
  const monthOf = (event: any) => event.at ? new Date(event.at).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' }) : 'Undated'
  return (
    <div className="p-6 max-w-3xl">
      <div className="flex flex-wrap gap-2 mb-4">
        {filters.map(name => (
          <button key={name} onClick={() => setFilter(name)} aria-pressed={filter === name}
            className={`text-sm px-3 py-1 border capitalize ${filter === name ? 'bg-slate-800 text-white border-slate-800' : 'bg-white border-slate-300'}`}>{name}</button>
        ))}
      </div>
      {!shown.length && <p className="text-slate-500">Nothing of this kind on the timeline.</p>}
      <ol className="border-l-2 border-slate-200 ml-2">
        {shown.map((event, index) => {
          const month = monthOf(event)
          const heading = index === 0 || month !== monthOf(shown[index - 1])
          const isFact = event.kind.startsWith('fact:')
          return (
            <li key={index} className="pl-4 pb-2">
              {heading && <p className="text-xs font-bold uppercase tracking-wide text-slate-500 mt-4 mb-1">{month}</p>}
              <div className="flex gap-3 text-sm items-baseline">
                <span className="text-slate-500 w-24 shrink-0">{fmtDate(event.at)}</span>
                <span>{KIND_LABEL[event.kind] && <span className="text-slate-500">{KIND_LABEL[event.kind]}: </span>}{isFact && <span className="text-slate-500">{event.kind.slice(5).replace('_', ' ')}: </span>}{event.title}
                  <span className="text-slate-500"> · {event.state?.replace('_', ' ')}</span>
                  {isFact && <button onClick={() => onSelectFact(event.ref_id)} className="ml-2 text-blue-700 hover:underline">source →</button>}
                </span>
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function Search({ patientId, onSelectFact }: { patientId: string; onSelectFact: (id: string) => void }) {
  const [q, setQ] = useState('')
  const [result, setResult] = useState<any | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!q.trim()) return
    setBusy(true)
    setError('')
    try { setResult(await post(`/patients/${patientId}/search`, { q })) } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="p-6 max-w-3xl">
      <form onSubmit={submit} className="flex gap-2 mb-4">
        <input value={q} onChange={e => setQ(e.target.value)} aria-label="Search this patient's record"
          placeholder="Ask about this patient, e.g. “any sulfa allergy?” or “last creatinine”"
          className="flex-1 border border-slate-300 px-3 py-2 bg-white" />
        <button disabled={busy} className="bg-blue-600 text-white px-4 font-medium disabled:opacity-50">{busy ? 'Searching…' : 'Search'}</button>
      </form>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {result && (
        <>
          <p className="bg-white border border-slate-200 p-4 mb-4">{result.answer}</p>
          <ol className="space-y-2">
            {result.evidence.map((fact: any, index: number) => (
              <li key={fact.id}>
                <button onClick={() => onSelectFact(fact.id)} className="w-full text-left bg-white border border-slate-200 hover:border-blue-500 p-3 text-sm">
                  <span className="font-mono text-xs bg-blue-50 border border-blue-200 text-blue-800 px-1.5 py-0.5 mr-2">[{index + 1}]</span>
                  <span className="font-medium">{fact.assertion === 'denied' ? 'Denied: ' : ''}{fact.display} {factValue(fact)}</span>
                  <span className="text-slate-500"> · {fmtDate(fact.effective_at)} · {fact.fact_type.replace('_', ' ')} · {(STATE[fact.state] || STATE.extracted).label}</span>
                  {fact.raw_text && <span className="block text-slate-600 mt-1">“{fact.raw_text}” — open source →</span>}
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
      <p className="text-xs text-slate-500 mt-6">Answers are assembled only from facts in this chart, each with its source. Every search is written to the audit log.</p>
    </div>
  )
}

'use client'

import { useEffect, useRef, useState } from 'react'
import { api, fileUrl, fmtClock, fmtDate } from '../lib/api'

/** Shows exactly where a fact came from: the box on the PDF page, or the spoken sentence. */
export default function SourceViewer({ fact, onSelectFact }: { fact: any | null; onSelectFact: (id: string) => void }) {
  if (!fact) {
    return (
      <div className="text-slate-500 text-center px-6 mt-24">
        <p>Select a fact, a sentence in the note, or a step in an alert to see its exact source.</p>
      </div>
    )
  }
  return (
    <div className="w-full">
      <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-2">Source of “{fact.display}”</h3>
      {fact.source === 'document' && <DocumentSource fact={fact} />}
      {fact.source === 'audio' && <AudioSource key={fact.recording_id} fact={fact} />}
      {fact.source === 'manual' && <DerivedSource fact={fact} onSelectFact={onSelectFact} />}
    </div>
  )
}

function DocumentSource({ fact }: { fact: any }) {
  const box = fact.bbox
  return (
    <figure className="bg-white border border-slate-200 overflow-hidden">
      <figcaption className="bg-slate-800 text-white px-3 py-2 text-sm flex justify-between">
        <span>{fact.document_name || 'Document'} · page {fact.page_no}</span>
        <span className="opacity-75">{fmtDate(fact.effective_at)}</span>
      </figcaption>
      <div className="relative">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={fileUrl(`/documents/${fact.document_id}/pages/${fact.page_no}.png`)} alt={`Page ${fact.page_no} of ${fact.document_name}`} className="w-full block" />
        {box && (
          <div
            className="absolute border-2 border-red-600 bg-red-500/20 animate-pulse"
            style={{
              left: `${(box.x - 0.006) * 100}%`, top: `${(box.y - 0.004) * 100}%`,
              width: `${(box.w + 0.012) * 100}%`, height: `${(box.h + 0.008) * 100}%`,
            }}
            title={fact.raw_text}
          />
        )}
      </div>
      <p className="px-3 py-2 text-sm text-slate-600 border-t border-slate-200">Text at this location: “{fact.raw_text}”</p>
    </figure>
  )
}

/** The rows of a scan that the OCR could not read or was unsure of, boxed on the page. */
export function ScanReview({ documentId, onClose }: { documentId: string; onClose: () => void }) {
  const [doc, setDoc] = useState<any | null>(null)
  const [error, setError] = useState('')

  useEffect(() => { api(`/documents/${documentId}`).then(setDoc).catch(e => setError(e.message)) }, [documentId])

  const limits = doc?.thresholds
  const flagged: any[] = doc ? doc.blocks.filter((b: any) => b.confidence < limits.review_below) : []
  const pages = [...new Set(flagged.map(b => b.page_no))]
  const unreadable = (block: any) => block.confidence < limits.unreadable_below

  return (
    <figure className="bg-white border border-slate-200 overflow-hidden mb-5">
      <figcaption className="bg-slate-800 text-white px-3 py-2 text-sm flex justify-between">
        <span>Scan check · {doc?.original_name || 'document'}</span>
        <button onClick={onClose} aria-label="Close scan check" className="opacity-75 hover:opacity-100">×</button>
      </figcaption>
      {error && <p className="p-3 text-red-700 text-sm">{error}</p>}
      {!doc && !error && <p className="p-3 text-slate-500 text-sm">Loading…</p>}
      {doc && !flagged.length && <p className="p-3 text-sm text-slate-600">Every row on this scan was read with confidence.</p>}
      {pages.map(page => (
        <div key={page} className="relative">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={fileUrl(`/documents/${documentId}/pages/${page}.png`)} alt={`Page ${page} of ${doc.original_name}`} className="w-full block" />
          {flagged.filter(b => b.page_no === page).map(block => (
            <div key={block.id} title={unreadable(block) ? 'Could not be read' : `Read with ${Math.round(block.confidence * 100)}% confidence`}
              className={`absolute border-2 border-amber-500 ${unreadable(block) ? 'bg-amber-400/30' : 'border-dashed'}`}
              style={{
                left: `${(block.x - 0.006) * 100}%`, top: `${(block.y - 0.004) * 100}%`,
                width: `${(block.w + 0.012) * 100}%`, height: `${(block.h + 0.008) * 100}%`,
              }} />
          ))}
        </div>
      ))}
      {flagged.length > 0 && (
        <div className="px-3 py-2 text-sm border-t border-slate-200">
          <p className="text-slate-600 mb-1">Check these rows against the paper. Unreadable rows were not used; no fact was guessed from them.</p>
          <ul className="space-y-1">
            {flagged.map(block => (
              <li key={block.id}>
                <span className="font-semibold" style={{ color: 'var(--state-extracted)' }}>
                  {unreadable(block) ? 'Could not be read' : `Low confidence (${Math.round(block.confidence * 100)}%)`}
                </span>
                {' · '}page {block.page_no} · {block.text ? <>what the OCR made of it: “{block.text}”</> : 'nothing legible'}
              </li>
            ))}
          </ul>
        </div>
      )}
    </figure>
  )
}

function AudioSource({ fact }: { fact: any }) {
  const [recording, setRecording] = useState<any | null>(null)
  const [error, setError] = useState('')
  const audio = useRef<HTMLAudioElement>(null)

  useEffect(() => {
    api(`/recordings/${fact.recording_id}`).then(setRecording).catch(e => setError(e.message))
  }, [fact.recording_id])

  // A browser recording carries no length, so the player cannot seek in it until it has
  // been made to find the end once: jump far past it, then come back.
  const findLength = () => {
    const player = audio.current
    if (!player || player.duration !== Infinity) return
    player.ontimeupdate = () => { player.ontimeupdate = null; player.currentTime = 0 }
    player.currentTime = 1e9
  }

  const cited = new Set<string>(fact.segment_ids || [])
  const play = () => {
    if (!audio.current) return
    audio.current.currentTime = fact.audio_start_ms / 1000
    audio.current.play()
  }

  return (
    <div className="bg-white border border-slate-200 overflow-hidden">
      <div className="bg-slate-800 text-white px-3 py-2 text-sm flex justify-between">
        <span>{recording?.original_name || 'Consult recording'}</span>
        <span>{fmtClock(fact.audio_start_ms)}–{fmtClock(fact.audio_end_ms)}</span>
      </div>
      {error && <p className="p-3 text-red-700 text-sm">{error}</p>}
      {recording?.has_audio && (
        <div className="p-3 border-b border-slate-200 flex items-center gap-3">
          <audio ref={audio} controls preload="metadata" onLoadedMetadata={findLength} src={fileUrl(`/recordings/${fact.recording_id}/audio`)} className="flex-1 h-9" />
          <button onClick={play} className="text-sm bg-blue-600 text-white px-3 py-1.5 hover:bg-blue-700">Play span</button>
        </div>
      )}
      {recording && !recording.has_audio && (
        <p className="px-3 py-2 text-xs text-slate-500 border-b border-slate-200">Typed transcript — no audio to play.</p>
      )}
      <ol className="p-3 space-y-1 max-h-[28rem] overflow-y-auto text-sm">
        {!recording && !error && <li className="text-slate-500">Loading transcript…</li>}
        {recording?.segments.map((segment: any) => (
          <li key={segment.id} className={`flex gap-3 px-2 py-1.5 ${cited.has(segment.id) ? 'bg-yellow-100 border-l-4 border-yellow-500 font-medium' : ''}`}>
            <span className="font-mono text-xs text-slate-500 pt-0.5 shrink-0">{fmtClock(segment.start_ms)}</span>
            <span>
              {segment.speaker !== 'unknown' && <span className="text-slate-500 capitalize">{segment.speaker}: </span>}
              {segment.text}
              {cited.has(segment.id) && <span className="ml-2 text-xs text-yellow-800">cited</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function DerivedSource({ fact, onSelectFact }: { fact: any; onSelectFact: (id: string) => void }) {
  const inputs = fact.dose?.inputs
  if (!fact.dose?.formula) {
    return <p className="bg-white border border-slate-200 p-4 text-sm text-slate-600">Entered manually by {fact.created_by}.</p>
  }
  return (
    <div className="bg-white border border-slate-200 p-4 text-sm">
      <p className="font-semibold mb-2">Computed by deterministic code, not by a model</p>
      <dl className="grid grid-cols-2 gap-y-1">
        <dt className="text-slate-500">Formula</dt><dd className="font-mono">{fact.dose.formula}</dd>
        {inputs && Object.entries(inputs).map(([name, value]) => (
          <div key={name} className="contents"><dt className="text-slate-500">{name.replaceAll('_', ' ')}</dt><dd className="font-mono">{String(value)}</dd></div>
        ))}
        <dt className="text-slate-500">Result</dt><dd className="font-mono font-semibold">{fact.value_num} {fact.unit}</dd>
      </dl>
      {fact.dose.input_fact && (
        <button onClick={() => onSelectFact(fact.dose.input_fact)} className="mt-3 text-blue-700 hover:underline">
          View the source of the input value →
        </button>
      )}
    </div>
  )
}

'use client'

import { useEffect, useRef, useState } from 'react'
import { fmtClock } from '../lib/api'

// first format the browser can record; the API picks the decoder from the file extension
const FORMATS = [['audio/webm;codecs=opus', 'webm'], ['audio/mp4', 'm4a'], ['audio/ogg;codecs=opus', 'ogg']]
const MAX_MS = 30 * 60 * 1000  // stays far below the 25 MB upload limit at this bitrate

/** Records the consult from the microphone and hands the finished file to the normal upload. */
export default function ConsultRecorder({ disabled, onRecorded }: { disabled: boolean; onRecorded: (file: File) => void }) {
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const keep = useRef(true)

  const finish = (save: boolean) => {
    keep.current = save
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }

  // leaving the chart mid-recording discards it and releases the microphone
  useEffect(() => () => finish(false), [])

  useEffect(() => {
    if (!recording) return
    const started = Date.now()
    const timer = setInterval(() => {
      setElapsed(Date.now() - started)
      if (Date.now() - started >= MAX_MS) finish(true)
    }, 500)
    return () => clearInterval(timer)
  }, [recording])

  const start = async () => {
    setError('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('This browser cannot record here. Open the app on http://localhost or over HTTPS, in Chrome, Edge or Firefox.')
      return
    }
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
    } catch {
      setError('The microphone is blocked or missing. Allow microphone access for this site and try again.')
      return
    }
    const format = FORMATS.find(([mime]) => MediaRecorder.isTypeSupported(mime))
    const rec = new MediaRecorder(stream, { mimeType: format?.[0], audioBitsPerSecond: 48000 })
    const chunks: Blob[] = []
    rec.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
    rec.onstop = () => {
      stream.getTracks().forEach(track => track.stop())
      setRecording(false)
      setElapsed(0)
      if (!keep.current || !chunks.length) return
      const now = new Date()
      const stamp = `${now.toLocaleDateString('en-CA')}-${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`
      onRecorded(new File(chunks, `consult-${stamp}.${format?.[1] || 'webm'}`, { type: rec.mimeType }))
    }
    keep.current = true
    recorder.current = rec
    rec.start(1000)
    setRecording(true)
  }

  if (!recording) {
    return (
      <div className="flex-1 min-w-40">
        <button onClick={start} disabled={disabled}
          className="w-full border border-red-700 text-red-700 bg-white font-medium py-2 px-4 text-sm hover:bg-red-50 disabled:opacity-40">
          ● Record consult
        </button>
        {error && <p role="alert" className="text-sm text-red-700 mt-1">{error}</p>}
      </div>
    )
  }
  return (
    <div className="basis-full flex flex-wrap items-center gap-2 border border-red-700 bg-red-50 px-3 py-2 text-sm" role="status">
      <span className="font-semibold text-red-700 animate-pulse">● Recording</span>
      <span className="font-mono mr-auto">{fmtClock(elapsed)}</span>
      <button onClick={() => finish(true)} className="bg-red-700 text-white font-medium px-3 py-1 hover:bg-red-800">■ Stop &amp; transcribe</button>
      <button onClick={() => finish(false)} className="border border-slate-400 bg-white px-3 py-1 hover:bg-slate-100">Discard</button>
      <p className="basis-full text-xs text-slate-600">Audio is sent for transcription as recorded; only its transcript is redacted.</p>
    </div>
  )
}

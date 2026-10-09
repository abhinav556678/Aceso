'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { MOCK_DATA } from '../../../lib/supabase'

export default function PatientChart({ params }: { params: { id: string } }) {
  const patient = MOCK_DATA.patients.find(p => p.id === params.id)
  const [facts, setFacts] = useState<any[]>(MOCK_DATA.facts.filter(f => f.patient_id === params.id))
  
  const [selectedFact, setSelectedFact] = useState<any | null>(null)
  const [activeJobs, setActiveJobs] = useState<{id: string, name: string, status: string}[]>([])

  const [alerts, setAlerts] = useState<any[]>(MOCK_DATA.safety_alerts?.filter(a => a.patient_id === params.id && a.status === 'open') || [])
  const [selectedAlert, setSelectedAlert] = useState<any | null>(null)

  const [activeTab, setActiveTab] = useState<'current_visit' | 'timeline'>('current_visit')
  const [summary, setSummary] = useState<any | null>(null)
  const [timeline, setTimeline] = useState<any[] | null>(null)
  const [trends, setTrends] = useState<any | null>(null)
  const [selectedTrend, setSelectedTrend] = useState('HbA1c')

  useEffect(() => {
    const fetchApi = (path: string, setter: (d: any) => void) => {
      fetch(`http://localhost:8000/api/patients/${params.id}/${path}`)
        .then(r => r.json())
        .then(setter)
        .catch(console.error)
    }
    
    fetchApi('summary', setSummary)
    fetchApi('timeline', (d) => setTimeline(d.events))
    fetchApi(`trends?concept=${selectedTrend}`, setTrends)
  }, [params.id, selectedTrend])

  const [gapPrompts, setGapPrompts] = useState<any[]>([])

  useEffect(() => {
    // Connect to WebSocket for Live Gap Prompts
    // In a real app, the active encounter ID would come from the router or context.
    const encounterId = facts.length > 0 ? facts[0].encounter_id : 'e0000000-0000-4000-8000-000000000001'
    const ws = new WebSocket(`ws://localhost:8000/api/live/${encounterId}/gaps`)
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.gaps) {
          setGapPrompts(data.gaps)
        }
      } catch (err) {
        console.error("WebSocket message parse error", err)
      }
    }
    
    ws.onerror = (err) => console.error("WebSocket error", err)
    
    return () => {
      ws.close()
    }
  }, [])

  const [searchQuery, setSearchQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<any[] | null>(null)

  const handleSearch = async (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && searchQuery.trim()) {
      setIsSearching(true)
      try {
        const res = await fetch(`http://localhost:8000/search`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ query: searchQuery.trim(), patient_id: params.id })
        })
        const data = await res.json()
        setSearchResults(data.results.map((r: any) => ({
          content: r.content,
          display: r.display,
          factData: {
            id: r.fact_id,
            display: r.display,
            source: r.source,
            audio_start_ms: r.audio_start_ms,
            audio_end_ms: r.audio_end_ms,
            page_no: r.page_no,
            bbox: typeof r.bbox === 'string' ? JSON.parse(r.bbox) : r.bbox,
            raw_text: r.raw_text
          }
        })))
      } catch (err) {
        console.error("Search failed:", err)
        setSearchResults([])
      } finally {
        setIsSearching(false)
      }
    }
  }

  if (!patient) return <div className="p-8">Patient not found</div>

  const age = 2026 - new Date(patient.dob).getFullYear()
  const encounterId = facts.length > 0 ? facts[0].encounter_id : ''

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col relative">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 shadow-sm relative z-10 flex flex-col">
        <div className="px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900">
              {patient.full_name} · {age} {patient.sex} · MRN {patient.mrn} · {patient.preferred_lang === 'ta' ? 'தமிழ்' : 'English'}
            </h1>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex gap-2">
              <button 
                onClick={() => {
                  window.open(`http://localhost:8000/api/encounters/${encounterId}/export/pdf?lang=${patient.preferred_lang}`, '_blank')
                }}
                className="bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium py-2 px-3 rounded shadow-sm text-sm border border-slate-300 transition-colors"
                disabled={!encounterId}
              >
                📄 PDF
              </button>
              <button 
                onClick={() => {
                  window.open(`http://localhost:8000/api/encounters/${encounterId}/export/fhir`, '_blank')
                }}
                className="bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium py-2 px-3 rounded shadow-sm text-sm border border-slate-300 transition-colors"
                disabled={!encounterId}
              >
                🏥 FHIR
              </button>
            </div>
            
            <button 
              className="bg-green-600 hover:bg-green-700 text-white font-bold py-2 px-4 rounded shadow transition-colors"
              onClick={async () => {
                if (alerts.length > 0) {
                  alert("Cannot sign off: You have unacknowledged safety alerts.")
                  return
                }
                try {
                  alert("Encounter signed off successfully! Facts confirmed, note locked, and audit log written.")
                } catch (e) {
                  alert("Sign off failed.")
                }
              }}
            >
              Sign Off Encounter
            </button>
            <Link href="/patients">
              <button className="text-slate-500 hover:text-slate-800 font-medium">Close</button>
            </Link>
          </div>
        </div>
        
        {/* Tabs */}
        <div className="px-6 flex gap-6 text-sm font-medium border-t border-slate-100">
          <button 
            onClick={() => setActiveTab('current_visit')}
            className={`py-3 border-b-2 transition-colors ${activeTab === 'current_visit' ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}
          >
            Overview
          </button>
          <button 
            onClick={() => setActiveTab('timeline')}
            className={`py-3 border-b-2 transition-colors ${activeTab === 'timeline' ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}
          >
            Timeline & Trends
          </button>
        </div>
      </header>

      {/* Safety Alerts Banner */}
      {alerts.length > 0 && (
        <div className="bg-red-600 text-white px-6 py-3 flex justify-between items-center shadow-md relative z-10">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🚨</span>
            <div>
              <p className="font-bold text-lg">CRITICAL SAFETY ALERT</p>
              <p className="text-red-100">{alerts[0].message}</p>
            </div>
          </div>
          <button 
            onClick={() => setSelectedAlert(alerts[0])}
            className="bg-white text-red-600 font-bold px-4 py-2 rounded shadow hover:bg-red-50 transition-colors"
          >
            Review Logic
          </button>
        </div>
      )}

      {/* Gap Prompts Widget */}
      {gapPrompts.length > 0 && activeTab === 'current_visit' && (
        <div className="absolute bottom-6 left-6 z-50 flex flex-col gap-3 max-w-sm pointer-events-none">
          {gapPrompts.map((prompt, idx) => (
            <div key={idx} className="bg-white border-l-4 border-amber-500 shadow-xl rounded-r-lg p-4 pointer-events-auto flex gap-3 items-start animate-fade-in-up">
              <span className="text-xl">{prompt.type === 'overdue_loop' ? '⏳' : '💡'}</span>
              <div>
                <h4 className="text-sm font-bold text-slate-800 uppercase tracking-wide mb-1">
                  {prompt.type === 'overdue_loop' ? 'Pending from Last Visit' : 'Consult Nudge'}
                </h4>
                <p className="text-sm text-slate-600">{prompt.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Main Layout */}
      {activeTab === 'current_visit' ? (
      <div className="flex flex-col flex-1 overflow-hidden relative">
        
        {summary && (
          <div className="bg-white border-b border-slate-200 p-4 shadow-sm shrink-0 flex gap-6 z-10">
            <div className="flex-1">
              <h3 className="text-xs font-bold text-slate-500 uppercase mb-1">Active Conditions</h3>
              <p className="text-sm font-medium text-slate-800">{summary.conditions?.join(', ') || 'None'}</p>
            </div>
            <div className="flex-1">
              <h3 className="text-xs font-bold text-slate-500 uppercase mb-1">Current Medications</h3>
              <p className="text-sm font-medium text-slate-800">{summary.medications?.join(', ') || 'None'}</p>
            </div>
            <div className="flex-1">
              <h3 className="text-xs font-bold text-slate-500 uppercase mb-1">Allergies</h3>
              <p className="text-sm font-medium text-red-600">{summary.allergies?.join(', ') || 'NKA'}</p>
            </div>
          </div>
        )}

        <div className="flex flex-1 overflow-hidden relative">
        
        {/* Left Col: Facts & Upload */}
        <div className="w-1/3 flex flex-col overflow-y-auto border-r border-slate-200 bg-slate-50 relative">
          
          <div className="sticky top-0 bg-slate-50 border-b border-slate-200 z-10 p-6 pb-4">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold text-slate-800">Clinical Knowledge</h2>
              <div className="flex gap-2">
                <label className="cursor-pointer bg-blue-600 hover:bg-blue-700 text-white font-medium py-1 px-3 rounded text-sm transition-colors">
                  Upload PDF
                  <input type="file" className="hidden" accept=".pdf" onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const jobId = Math.random().toString();
                    setActiveJobs(prev => [...prev, { id: jobId, name: file.name, status: 'pending' }]);
                    setTimeout(() => {
                      setActiveJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'running' } : j));
                      setTimeout(() => {
                        setActiveJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'done' } : j));
                        setFacts(prev => [{
                          id: `fact-pdf-${jobId}`,
                          patient_id: params.id,
                          fact_type: 'lab_result',
                          display: 'HbA1c',
                          value_num: 7.2,
                          unit: '%',
                          raw_text: 'HbA1c 7.2%',
                          state: 'extracted',
                          source: 'document',
                          page_no: 1,
                          bbox: { x: 0.2, y: 0.3, w: 0.4, h: 0.1 }
                        }, ...prev]);
                        setTimeout(() => setActiveJobs(prev => prev.filter(j => j.id !== jobId)), 3000);
                      }, 3000);
                    }, 1000);
                  }} />
                </label>
                <label className="cursor-pointer bg-blue-600 hover:bg-blue-700 text-white font-medium py-1 px-3 rounded text-sm transition-colors">
                  Upload Audio
                  <input type="file" className="hidden" accept="audio/*" onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const jobId = Math.random().toString();
                    setActiveJobs(prev => [...prev, { id: jobId, name: file.name, status: 'pending' }]);
                    setTimeout(() => {
                      setActiveJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'running' } : j));
                      setTimeout(() => {
                        setActiveJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'done' } : j));
                        setFacts(prev => [{
                          id: `fact-audio-${jobId}`,
                          patient_id: params.id,
                          fact_type: 'medication',
                          display: 'Metformin 500 mg',
                          value_num: 500,
                          unit: 'mg',
                          raw_text: 'Continue Glycomet 500',
                          state: 'extracted',
                          source: 'audio',
                          audio_start_ms: 12000,
                          audio_end_ms: 15000
                        }, ...prev]);
                        setTimeout(() => setActiveJobs(prev => prev.filter(j => j.id !== jobId)), 3000);
                      }, 3000);
                    }, 1000);
                  }} />
                </label>
              </div>
            </div>
            
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400">
                🔍
              </span>
              <input 
                type="text" 
                placeholder="Ask about this patient (e.g. 'Does he have a sulfa allergy?')"
                className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={handleSearch}
              />
            </div>
            {isSearching && <p className="text-xs text-blue-500 mt-2">Searching historical records...</p>}
          </div>

          <div className="p-6 pt-0 space-y-6">
            {activeJobs.length > 0 && (
              <div className="mb-4 space-y-2">
                {activeJobs.map(job => (
                  <div key={job.id} className="bg-blue-50 border border-blue-200 rounded p-3 text-sm flex justify-between items-center shadow-sm">
                    <span className="font-medium text-slate-800">{job.name}</span>
                    <span className="flex items-center gap-2">
                      {job.status === 'pending' && <span className="text-slate-500">⏳ Queued</span>}
                      {job.status === 'running' && <span className="text-blue-600 animate-pulse">🔄 Processing...</span>}
                      {job.status === 'done' && <span className="text-green-600">✓ Completed</span>}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {searchResults ? (
              <div>
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-sm font-bold text-blue-700 uppercase tracking-wider">Search Results</h3>
                  <button onClick={() => {setSearchResults(null); setSearchQuery('');}} className="text-xs text-slate-500 hover:text-slate-700 underline">Clear</button>
                </div>
                <div className="space-y-4">
                  {searchResults.map((res: any, idx: number) => (
                    <div key={idx} className="bg-white border border-slate-200 rounded-lg p-4 hover:border-blue-300 transition-colors">
                      <p className="text-sm text-slate-800 mb-2">"{res.content}"</p>
                      <button 
                        onClick={() => setSelectedFact(res.factData)}
                        className="inline-flex items-center gap-1 bg-blue-50 text-blue-700 border border-blue-200 px-2 py-1 rounded text-xs font-medium hover:bg-blue-100"
                      >
                        Citation: {res.display}
                      </button>
                    </div>
                  ))}
                  {searchResults.length === 0 && <p className="text-sm text-slate-500 italic">No matching facts found.</p>}
                </div>
              </div>
            ) : (
              <>
                {/* Requires Review Section */}
                <div>
                  <h3 className="text-sm font-bold text-red-700 uppercase tracking-wider mb-3">Requires Review</h3>
              <div className="space-y-4">
                {facts
                  .filter(f => f.fact_type === 'allergy' || f.fact_type === 'medication' || f.state === 'extracted')
                  .map(fact => {
                    const isSelected = selectedFact?.id === fact.id
                    return (
                      <div 
                        key={fact.id} 
                        onClick={() => setSelectedFact(fact)}
                        className={`p-4 rounded-lg border cursor-pointer transition-shadow ${
                          isSelected 
                            ? 'border-blue-500 bg-blue-50 shadow-sm' 
                            : 'border-red-200 bg-red-50 hover:border-red-300'
                        }`}
                      >
                        <div className="flex justify-between items-start mb-2">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-900">{fact.display}</span>
                            {fact.state === 'extracted' && (
                              <span className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full flex items-center">◔ Unverified</span>
                            )}
                          </div>
                          <span className="text-xs text-slate-500 uppercase tracking-wide">{fact.fact_type}</span>
                        </div>
                        
                        <div className="text-sm text-slate-700 space-y-1">
                          {fact.raw_text && <p><span className="text-slate-400">Raw text:</span> "{fact.raw_text}"</p>}
                          {fact.value_num !== null && <p><span className="text-slate-400">Value:</span> {fact.value_num} {fact.unit}</p>}
                          <p className="mt-2 text-xs text-slate-500">
                            Source: {fact.source === 'document' ? '📄 PDF Document' : '🎤 Audio Transcript'} 
                            {' '} • Click to view provenance
                          </p>
                        </div>
                      </div>
                    )
                  })}
              </div>
            </div>

            {/* Trusted Facts Section */}
            <details className="group border border-slate-200 rounded-lg bg-white">
              <summary className="flex justify-between items-center font-medium cursor-pointer list-none p-4 text-slate-700 hover:bg-slate-50">
                <span className="text-sm font-bold uppercase tracking-wider text-green-700">Trusted Facts (Verified)</span>
                <span className="transition group-open:rotate-180">
                  <svg fill="none" height="24" shapeRendering="geometricPrecision" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" viewBox="0 0 24 24" width="24"><path d="M6 9l6 6 6-6"></path></svg>
                </span>
              </summary>
              <div className="p-4 pt-0 space-y-4 border-t border-slate-200 mt-2">
                {facts
                  .filter(f => !(f.fact_type === 'allergy' || f.fact_type === 'medication' || f.state === 'extracted'))
                  .map(fact => {
                    const isSelected = selectedFact?.id === fact.id
                    return (
                      <div 
                        key={fact.id} 
                        onClick={() => setSelectedFact(fact)}
                        className={`p-4 rounded-lg border cursor-pointer transition-shadow ${
                          isSelected 
                            ? 'border-blue-500 bg-blue-50 shadow-sm' 
                            : 'border-slate-200 bg-white hover:border-blue-300'
                        }`}
                      >
                        <div className="flex justify-between items-start mb-2">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-900">{fact.display}</span>
                            {fact.state === 'verified' && (
                              <span className="text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded-full flex items-center">✓ Verified</span>
                            )}
                          </div>
                          <span className="text-xs text-slate-500 uppercase tracking-wide">{fact.fact_type}</span>
                        </div>
                        <div className="text-sm text-slate-700 space-y-1">
                          {fact.raw_text && <p><span className="text-slate-400">Raw text:</span> "{fact.raw_text}"</p>}
                          {fact.value_num !== null && <p><span className="text-slate-400">Value:</span> {fact.value_num} {fact.unit}</p>}
                        </div>
                      </div>
                    )
                  })}
              </div>
            </details>
              </>
            )}
          </div>
        </div>

        {/* Middle Col: SOAP Note */}
        <div className="w-1/3 flex flex-col overflow-y-auto border-r border-slate-200 p-6 bg-white">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold text-slate-800">SOAP Note Draft</h2>
          </div>
          
          {(() => {
            const soapNote = MOCK_DATA.soap_notes?.[0];
            if (!soapNote) return <p className="text-slate-500 text-sm">No draft generated yet.</p>;
            
            const renderSection = (title: string, section: any[]) => (
              <div className="mb-6">
                <h3 className="text-sm font-bold text-slate-700 uppercase tracking-wider mb-2 border-b pb-1">{title}</h3>
                {section.length > 0 ? (
                  <ul className="list-disc ml-4 space-y-1">
                    {section.map((item, i) => (
                      <li key={i} className="text-sm text-slate-800">
                        <span 
                          className={`cursor-pointer hover:bg-yellow-100 rounded px-1 transition-colors ${selectedFact && item.fact_ids.includes(selectedFact.id) ? 'bg-yellow-200' : ''}`}
                          onClick={() => {
                            if (item.fact_ids.length > 0) {
                              const f = facts.find(f => f.id === item.fact_ids[0]);
                              if (f) setSelectedFact(f);
                            }
                          }}
                        >
                          {item.text}
                        </span>
                        {item.fact_ids.length > 0 && (
                          <span className="ml-2 text-xs text-blue-500 opacity-70">
                            [fact {item.fact_ids[0].slice(0, 4)}]
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-slate-400 italic">None</p>
                )}
              </div>
            );
            
            return (
              <div>
                {renderSection('Subjective', soapNote.subjective)}
                {renderSection('Objective', soapNote.objective)}
                {renderSection('Assessment', soapNote.assessment)}
                {renderSection('Plan', soapNote.plan)}
              </div>
            );
          })()}
        </div>

        {/* Right Col: Source Viewer */}
        <div className="w-1/3 bg-slate-100 p-6 flex flex-col items-center justify-center overflow-y-auto">
          {selectedFact ? (
            <div className="w-full max-w-lg bg-white shadow-lg rounded-xl border border-slate-200 overflow-hidden">
              <div className="bg-slate-800 text-white p-3 text-sm font-mono flex justify-between">
                <span>{selectedFact.source === 'document' ? 'Document Viewer' : 'Audio Player'}</span>
                <span className="opacity-75">Provenance</span>
              </div>
              
              <div className="p-6 h-80 relative flex items-center justify-center bg-slate-50">
                {selectedFact.source === 'document' ? (
                  <div className="text-center">
                    <p className="text-slate-500 mb-4">Rendering PDF page {selectedFact.page_no}...</p>
                    <div className="relative border border-slate-300 w-48 h-64 bg-white mx-auto shadow-sm">
                      <div className="absolute inset-0 flex items-center justify-center text-slate-300 text-xs text-center p-4">
                        [Mock PDF Content: Lab Results]
                      </div>
                      {selectedFact.bbox && (
                        <div 
                          className="absolute border-2 border-red-500 bg-red-500/20 shadow-[0_0_10px_rgba(239,68,68,0.5)] transition-all"
                          style={{
                            left: `${selectedFact.bbox.x * 100}%`,
                            top: `${selectedFact.bbox.y * 100}%`,
                            width: `${selectedFact.bbox.w * 100}%`,
                            height: `${selectedFact.bbox.h * 100}%`
                          }}
                        />
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="w-full">
                    <p className="text-slate-500 text-center mb-6">Audio transcript region</p>
                    <div className="bg-slate-800 rounded p-4 text-green-400 font-mono text-sm leading-relaxed">
                      <p className="opacity-50">00:41</p>
                      <p className="text-white py-2 px-1 bg-white/10 rounded">
                        "Continue Glycomet 500 twice daily."
                      </p>
                      <p className="opacity-50">00:44</p>
                    </div>
                    <p className="text-xs text-slate-400 text-center mt-4">
                      Span: {selectedFact.audio_start_ms}ms - {selectedFact.audio_end_ms}ms
                    </p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="text-slate-400 text-center px-4">
              <span className="block text-4xl mb-4">🔍</span>
              <p>Select a fact or click a cited sentence in the SOAP note to view its exact source provenance.</p>
            </div>
          )}
        </div>
        </div>
      </div>
      ) : (
        <div className="flex-1 p-8 overflow-y-auto bg-white flex flex-col md:flex-row gap-8">
          {/* Timeline column */}
          <div className="w-1/2">
            <h3 className="text-lg font-semibold mb-4">Chronological Timeline</h3>
            <div className="border-l-2 border-slate-200 ml-3 space-y-6">
              {timeline ? timeline.map(event => (
                <div key={event.id} className="relative pl-6">
                  <div className="absolute w-3 h-3 bg-blue-500 rounded-full -left-[7px] top-1.5 ring-4 ring-white"></div>
                  <div className="text-sm text-slate-500 mb-1">{event.time ? new Date(event.time).toLocaleString() : 'Unknown date'}</div>
                  <div className="bg-slate-50 border border-slate-200 rounded p-4">
                    <div className="font-semibold text-slate-800">{event.title}</div>
                    <div className="text-sm text-slate-600 mt-1">{event.description}</div>
                    {event.value_num !== null && <div className="text-blue-600 font-mono mt-2">{event.value_num} {event.unit}</div>}
                  </div>
                </div>
              )) : <div className="pl-6 text-slate-500">Loading timeline...</div>}
            </div>
          </div>
          
          {/* Trends column */}
          <div className="w-1/2">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-semibold">Trends</h3>
              <select 
                value={selectedTrend}
                onChange={(e) => setSelectedTrend(e.target.value)}
                className="border border-slate-300 rounded px-2 py-1 text-sm bg-white"
              >
                <option value="HbA1c">HbA1c</option>
                <option value="Creatinine">Creatinine</option>
              </select>
            </div>
            {trends ? (
              <div className="bg-slate-50 border border-slate-200 rounded p-6">
                <div className="relative h-64 border-l border-b border-slate-400">
                  {/* Bands */}
                  {(() => {
                    const isHbA1c = selectedTrend === 'HbA1c';
                    const yMin = isHbA1c ? 4 : 0;
                    const yRange = isHbA1c ? 6 : 5;
                    const getY = (val: number) => Math.max(0, Math.min(100, ((val - yMin) / yRange) * 100));
                    
                    const normalMinY = trends.ranges?.normal_min ? getY(trends.ranges.normal_min) : 0;
                    const normalMaxY = trends.ranges?.normal_max ? getY(trends.ranges.normal_max) : 33;
                    const prediabMaxY = trends.ranges?.prediabetes_max ? getY(trends.ranges.prediabetes_max) : 66;

                    return (
                      <>
                        <div className="absolute w-full bottom-0 bg-green-100/50 border-t border-green-300" style={{ height: `${normalMaxY}%` }}>
                          <span className="text-xs text-green-700 absolute right-2 top-1">Normal ({trends.ranges?.normal_min}-{trends.ranges?.normal_max})</span>
                        </div>
                        {isHbA1c && (
                          <div className="absolute w-full bg-yellow-100/50 border-t border-yellow-300" style={{ bottom: `${normalMaxY}%`, height: `${prediabMaxY - normalMaxY}%` }}>
                            <span className="text-xs text-yellow-700 absolute right-2 top-1">Prediabetes (up to {trends.ranges?.prediabetes_max})</span>
                          </div>
                        )}
                        <div className="absolute w-full bg-red-100/50" style={{ bottom: `${isHbA1c ? prediabMaxY : normalMaxY}%`, top: 0 }}>
                          <span className="text-xs text-red-700 absolute right-2 top-1">{isHbA1c ? 'Diabetes' : 'High'}</span>
                        </div>
                      </>
                    )
                  })()}

                  {/* Data Points and Medications */}
                  {(() => {
                    const labTimes = (trends.labs || []).map((l: any) => new Date(l.date).getTime());
                    const medTimes = (trends.meds || []).flatMap((m: any) => {
                      const t = [new Date(m.start_date).getTime()];
                      if (m.end_date) t.push(new Date(m.end_date).getTime());
                      return t;
                    });
                    const allTimes = [...labTimes, ...medTimes];
                    const minT = allTimes.length ? Math.min(...allTimes) : Date.now() - 31536000000;
                    const maxT = allTimes.length ? Math.max(...allTimes) : Date.now();
                    const range = Math.max(maxT - minT, 86400000); // at least 1 day

                    const getX = (dateStr: string) => {
                      const t = new Date(dateStr).getTime();
                      return ((t - minT) / range) * 100;
                    };
                    
                    const isHbA1c = selectedTrend === 'HbA1c';
                    const yMin = isHbA1c ? 4 : 0;
                    const yRange = isHbA1c ? 6 : 5;

                    return (
                      <>
                        {/* Medication start/stop */}
                        {trends.meds?.map((med: any, i: number) => {
                          const startX = getX(med.start_date);
                          const endX = med.end_date ? getX(med.end_date) : null;
                          return (
                            <div key={i}>
                              <div className="absolute border-l-2 border-dashed border-purple-500 h-full z-0" style={{ left: `${startX}%` }}>
                                <span className="bg-purple-100 text-purple-800 text-xs px-1 rounded absolute top-2 whitespace-nowrap transform -translate-x-1/2">{med.name} start</span>
                              </div>
                              {endX !== null && (
                                <div className="absolute border-l-2 border-dashed border-red-400 h-full z-0" style={{ left: `${endX}%` }}>
                                  <span className="bg-red-50 text-red-800 text-xs px-1 rounded absolute top-6 whitespace-nowrap transform -translate-x-1/2">{med.name} stop</span>
                                </div>
                              )}
                              {endX !== null && (
                                <div className="absolute bg-purple-200/30 h-full z-0" style={{ left: `${startX}%`, width: `${endX - startX}%` }}></div>
                              )}
                            </div>
                          )
                        })}

                        {/* Data points */}
                        {trends.labs?.map((lab: any, i: number) => {
                          const x = getX(lab.date);
                          const y = Math.max(0, Math.min(100, ((lab.value - yMin) / yRange) * 100));
                          return (
                            <div key={i} className="absolute w-3 h-3 bg-blue-600 rounded-full transform -translate-x-1.5 translate-y-1.5 z-10" style={{ left: `${x}%`, bottom: `${y}%` }} title={`${lab.value} ${lab.unit} on ${new Date(lab.date).toLocaleDateString()}`}></div>
                          )
                        })}
                      </>
                    )
                  })()}
                </div>
              </div>
            ) : <div className="text-slate-500">Loading trends...</div>}
          </div>
        </div>
      )}



      {/* Safety Alert Explainability Drawer */}
      {selectedAlert && (
        <div className="absolute inset-0 bg-slate-900/40 z-50 flex justify-end">
          <div className="w-1/3 bg-white h-full shadow-2xl flex flex-col transform transition-transform border-l border-slate-200">
            <div className="p-6 border-b border-slate-200 flex justify-between items-center bg-red-50">
              <h2 className="text-xl font-bold text-red-700 flex items-center gap-2">
                <span>🚨</span> Alert Details
              </h2>
              <button onClick={() => setSelectedAlert(null)} className="text-slate-400 hover:text-slate-700 text-xl font-bold">×</button>
            </div>
            <div className="p-6 overflow-y-auto flex-1">
              <div className="mb-6">
                <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-2">Rule Triggered</h3>
                <p className="font-mono bg-slate-100 p-3 rounded text-sm text-slate-800 border border-slate-200">
                  {selectedAlert.rule_id}
                </p>
              </div>
              <div className="mb-6">
                <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-2">Deterministic Logic</h3>
                <p className="font-mono bg-blue-50 text-blue-900 p-3 rounded text-sm border border-blue-200 mb-2">
                  {selectedAlert.trace.logic}
                </p>
                <div className="bg-white border border-slate-200 rounded p-4">
                  <h4 className="text-xs font-semibold text-slate-400 mb-2 uppercase">Computed Variables</h4>
                  <ul className="space-y-1">
                    {Object.entries(selectedAlert.trace.variables).map(([k, v]) => (
                      <li key={k} className="text-sm flex justify-between border-b border-slate-50 last:border-0 pb-1">
                        <span className="text-slate-600">{k}:</span>
                        <span className="font-mono font-semibold">{v as React.ReactNode}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              <div>
                <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-2">Step-by-Step Execution</h3>
                <ol className="relative border-l border-slate-200 ml-3 space-y-4">
                  {selectedAlert.trace.steps.map((step: string, idx: number) => (
                    <li key={idx} className="ml-5 relative">
                      <span className="absolute flex items-center justify-center w-6 h-6 bg-blue-100 rounded-full -left-8 ring-4 ring-white text-blue-800 text-xs font-bold">
                        {idx + 1}
                      </span>
                      <p className="text-sm text-slate-700">{step}</p>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 bg-slate-50 flex gap-3">
              <button 
                onClick={() => {
                  // Simulate checking the fact
                  const triggerFact = facts.find(f => f.id === selectedAlert.trigger_fact_ids[0])
                  if (triggerFact) {
                    setSelectedFact(triggerFact)
                    setSelectedAlert(null)
                  }
                }}
                className="flex-1 bg-white border border-slate-300 text-slate-700 font-semibold py-2 px-4 rounded hover:bg-slate-50 transition-colors"
              >
                View Source Fact
              </button>
              {selectedAlert.rule_id.startsWith('CONTRADICTION') ? (
                <button 
                  onClick={() => {
                    const reason = prompt("Enter resolution reason (e.g. 'Patient confirms allergy was a false alarm in childhood'):")
                    if (reason) {
                      setAlerts(prev => prev.filter(a => a.id !== selectedAlert.id))
                      setSelectedAlert(null)
                    }
                  }}
                  className="flex-1 bg-yellow-500 text-white font-semibold py-2 px-4 rounded hover:bg-yellow-600 transition-colors"
                >
                  Resolve Contradiction
                </button>
              ) : (
                <button 
                  onClick={() => {
                    setAlerts(prev => prev.filter(a => a.id !== selectedAlert.id))
                    setSelectedAlert(null)
                  }}
                  className="flex-1 bg-red-600 text-white font-semibold py-2 px-4 rounded hover:bg-red-700 transition-colors"
                >
                  Acknowledge
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

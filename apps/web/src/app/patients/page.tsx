"use client"
import Link from 'next/link'
import { useState, useEffect } from 'react'
import { MOCK_DATA } from '../../lib/supabase'

export default function PatientsList() {
  const [overdueLoops, setOverdueLoops] = useState<any[]>([])

  useEffect(() => {
    fetch('http://localhost:8000/api/patients/dashboard/overdue_loops')
      .then(res => res.json())
      .then(data => setOverdueLoops(data.overdue_loops || []))
      .catch(console.error)
  }, [])

  return (
    <div className="min-h-screen bg-slate-50 p-8">
      <div className="max-w-4xl mx-auto">
        <header className="mb-8 flex justify-between items-center">
          <h1 className="text-2xl font-bold text-slate-900">Patient Directory</h1>
          <Link href="/" className="text-blue-600 hover:underline">Log out</Link>
        </header>
        
        {overdueLoops.length > 0 && (
          <div className="mb-8 bg-orange-50 border border-orange-200 rounded-lg p-6 shadow-sm">
            <h2 className="text-lg font-bold text-orange-800 flex items-center gap-2 mb-4">
              <span>⚠️</span> Overdue Follow-ups ({overdueLoops.length})
            </h2>
            <div className="space-y-3">
              {overdueLoops.map((loop, idx) => (
                <div key={idx} className="flex justify-between items-center bg-white p-3 rounded border border-orange-100 shadow-sm">
                  <div>
                    <span className="font-semibold text-slate-800">{loop.patient_name}</span>
                    <span className="mx-2 text-slate-400">|</span>
                    <span className="text-sm text-slate-600">{loop.description}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-xs font-medium text-orange-600 bg-orange-100 px-2 py-1 rounded">
                      Due: {new Date(loop.due_date).toLocaleDateString()}
                    </span>
                    <Link href={`/patients/${loop.patient_id}`} className="text-sm text-blue-600 hover:underline">
                      Review Chart
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-100 border-b border-slate-200">
                <th className="p-4 font-semibold text-slate-700">MRN</th>
                <th className="p-4 font-semibold text-slate-700">Name</th>
                <th className="p-4 font-semibold text-slate-700">Age / Sex</th>
                <th className="p-4 font-semibold text-slate-700">Action</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_DATA.patients.map((p) => {
                const age = 2026 - new Date(p.dob).getFullYear();
                return (
                  <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                    <td className="p-4 text-slate-600 font-mono">{p.mrn}</td>
                    <td className="p-4 font-medium text-slate-900">{p.full_name}</td>
                    <td className="p-4 text-slate-600">{age} {p.sex}</td>
                    <td className="p-4">
                      <Link 
                        href={`/patients/${p.id}`}
                        className="text-blue-600 hover:text-blue-800 font-medium"
                      >
                        Open Chart &rarr;
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}


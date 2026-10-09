'use client'

import { useRouter } from 'next/navigation'
import { Role, setRole } from '../lib/api'

const ACCOUNTS: { role: Role; name: string; can: string }[] = [
  { role: 'doctor', name: 'Dr. Rao', can: 'Review, confirm facts, handle alerts, sign off' },
  { role: 'nurse', name: 'Nurse Priya', can: 'View charts, upload documents, reject facts' },
  { role: 'admin', name: 'Admin Kumar', can: 'Demographics, audit log, chain verification' },
]

export default function Login() {
  const router = useRouter()
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-white border border-slate-200 p-8">
        <h1 className="text-2xl font-bold">ACESO</h1>
        <p className="text-slate-500 mb-6">Demo sign-in · synthetic patients only</p>
        <div className="space-y-3">
          {ACCOUNTS.map(account => (
            <button
              key={account.role}
              onClick={() => {
                setRole(account.role)
                router.push(account.role === 'admin' ? '/admin' : '/patients')
              }}
              className="w-full text-left border border-slate-300 hover:border-blue-500 hover:bg-blue-50 px-4 py-3 transition-colors"
            >
              <span className="font-semibold">{account.name}</span>
              <span className="ml-2 text-xs uppercase tracking-wide text-slate-500">{account.role}</span>
              <span className="block text-sm text-slate-600">{account.can}</span>
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-500 mt-6">
          This prototype uses a role switcher instead of passwords. Role rules are still enforced by the API and
          the database.
        </p>
      </div>
    </main>
  )
}

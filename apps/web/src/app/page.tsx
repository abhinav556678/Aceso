'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { api, getSession, post, Session, setSession } from '../lib/api'

const home = (session: Session) => (session.role === 'admin' ? '/admin' : '/patients')

export default function SignIn() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // already signed in: go straight to work
  useEffect(() => {
    if (getSession()) api<Session>('/session').then(session => router.replace(home(session))).catch(() => setSession(null))
  }, [router])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const session = await post<Session>('/login', { username, password })
      setSession(session)
      router.push(home(session))
    } catch (e: any) {
      setError(e.message)
      setBusy(false)
    }
  }

  const field = 'w-full border border-slate-300 bg-white px-3 py-2.5 mt-1.5'
  return (
    <main className="min-h-screen grid lg:grid-cols-[5fr_6fr]">
      <section className="hidden lg:flex flex-col justify-between bg-slate-900 text-white p-12">
        <p className="font-bold tracking-widest text-sm">ACESO</p>
        <div>
          <h1 className="text-3xl font-semibold leading-tight max-w-md">Clinical records where every fact shows its source.</h1>
          <ul className="mt-8 space-y-3 text-slate-300 max-w-md">
            <li>The model extracts. Deterministic code checks.</li>
            <li>Safety alerts show their full working.</li>
            <li>Nothing is final until a doctor signs.</li>
          </ul>
        </div>
        <p className="text-sm text-slate-400">Prototype · synthetic patients only</p>
      </section>

      <section className="flex items-center justify-center p-8 bg-white">
        <form onSubmit={submit} className="w-full max-w-sm">
          <p className="lg:hidden font-bold tracking-widest text-sm mb-8">ACESO</p>
          <h2 className="text-2xl font-semibold">Sign in</h2>
          <p className="text-slate-500 mt-1 mb-8">Use your clinic account.</p>

          <label className="block text-sm font-medium">
            Username
            <input value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" autoFocus required className={field} />
          </label>
          <label className="block text-sm font-medium mt-5">
            Password
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required className={field} />
          </label>

          {error && <p role="alert" className="mt-5 border border-red-300 bg-red-50 text-red-800 px-3 py-2 text-sm">{error}</p>}

          <button disabled={busy} className="mt-6 w-full bg-blue-600 text-white font-medium py-2.5 hover:bg-blue-700 disabled:opacity-50">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          <p className="text-xs text-slate-500 mt-8">Accounts: doctor, nurse and admin. Each sees only what its role allows.</p>
        </form>
      </section>
    </main>
  )
}

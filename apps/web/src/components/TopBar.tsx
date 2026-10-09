'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { getSession, Session, signOut } from '../lib/api'

/** The bar across the top of every signed-in page: where you are, who you are, and the way out. */
export default function TopBar() {
  // the session hint lives in localStorage, so it is only known once the page is in the browser
  const [session, setSession] = useState<Session | null>(null)
  useEffect(() => { setSession(getSession()) }, [])

  return (
    <header className="bg-slate-900 text-white px-6 h-12 flex items-center gap-8 shrink-0">
      <span className="font-bold tracking-widest text-sm">ACESO</span>
      <nav className="flex gap-6 text-sm text-slate-300" aria-label="Main">
        <Link href="/patients" className="hover:text-white">Patients</Link>
        {session?.role === 'admin' && <Link href="/admin" className="hover:text-white">Audit log</Link>}
      </nav>
      <div className="ml-auto flex items-center gap-4 text-sm">
        {session && <span className="text-slate-300">{session.name} <span className="text-slate-500">· {session.role}</span></span>}
        <button onClick={signOut} className="border border-slate-600 px-3 py-1 hover:bg-slate-800">Sign out</button>
      </div>
    </header>
  )
}

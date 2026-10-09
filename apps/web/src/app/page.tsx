import Link from 'next/link'

export default function Home() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="max-w-md w-full bg-white rounded-lg shadow p-8">
        <h1 className="text-2xl font-bold text-center mb-6">ACESO Login (Demo)</h1>
        
        <div className="space-y-4">
          <Link href="/patients" className="block w-full">
            <button className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded transition-colors">
              Login as Dr. Rao
            </button>
          </Link>
          
          <Link href="/patients" className="block w-full">
            <button className="w-full bg-slate-200 hover:bg-slate-300 text-slate-800 font-medium py-2 px-4 rounded transition-colors">
              Login as Nurse Priya
            </button>
          </Link>

          <Link href="/admin" className="block w-full">
            <button className="w-full bg-slate-200 hover:bg-slate-300 text-slate-800 font-medium py-2 px-4 rounded transition-colors">
              Login as Admin Kumar
            </button>
          </Link>
        </div>
      </div>
    </div>
  )
}

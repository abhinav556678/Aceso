// Single door to the FastAPI backend. The browser never talks to the database.

export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export type Role = 'doctor' | 'nurse' | 'admin'
export type Session = { name: string; role: Role }
const SESSION_KEY = 'aceso.session'

// What the page shows about who is signed in. The server decides access from its own
// session cookie; this copy only saves a round trip when drawing menus and buttons.
export function getSession(): Session | null {
  if (typeof window === 'undefined') return null
  try {
    return JSON.parse(window.localStorage.getItem(SESSION_KEY) || 'null')
  } catch {
    return null
  }
}

export function setSession(session: Session | null) {
  if (session) window.localStorage.setItem(SESSION_KEY, JSON.stringify(session))
  else window.localStorage.removeItem(SESSION_KEY)
}

export const getRole = (): Role | null => getSession()?.role ?? null

export async function signOut() {
  await fetch(`${API_URL}/api/logout`, { method: 'POST', credentials: 'include' }).catch(() => {})
  setSession(null)
  window.location.href = '/'
}

export class ApiError extends Error {
  status: number
  blockers: string[]
  constructor(status: number, message: string, blockers: string[] = []) {
    super(message)
    this.status = status
    this.blockers = blockers
  }
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(`${API_URL}/api${path}`, { ...init, headers, credentials: 'include' })
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is the backend running?`)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    if (response.status === 401 && path !== '/login' && window.location.pathname !== '/') {
      setSession(null)  // the session ended: back to the sign-in page
      window.location.href = '/'
    }
    const detail = body.detail
    if (Array.isArray(detail)) throw new ApiError(response.status, detail.map((d: any) => d.msg).join('; '))
    if (detail && typeof detail === 'object') throw new ApiError(response.status, detail.message, detail.blockers || [])
    throw new ApiError(response.status, detail || `Request failed (${response.status})`)
  }
  return response.json()
}

export const post = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

/** URL for things the browser loads by itself (images, audio, new tabs); the session cookie goes with them. */
export const fileUrl = (path: string): string => `${API_URL}/api${path}`

export const fmtDate = (value?: string | null) =>
  value ? new Date(value).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'

export const fmtClock = (ms: number) =>
  `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`

export const REASONS: Record<string, string> = {
  possible_omission: 'Mentioned in the source but not captured as a fact',
  unmapped_drug: 'Drug is not in our dictionary — not checked by the safety engine',
  unmapped_allergen: 'Allergen is not in our dictionary',
  unmapped_test: 'Test is not in our dictionary',
  unmapped_diagnosis: 'Diagnosis could not be coded',
  negation_conflict: 'The model and the negation check disagree on present / denied',
  out_of_plausible_range: 'Value is outside the physiologically possible range — likely a misread',
  ocr_mismatch: 'The value does not match the text at the cited location',
  low_ocr_confidence: 'Read from a scan with low confidence — check it against the page',
  read_by_handwriting_model: 'Handwritten on the page — the reading can be wrong, confirm it against the page',
  ocr_inexact_drug: 'Drug name read from a scan is not an exact dictionary match — confirm the drug',
  not_supported_by_transcript: 'The cited speech does not support this',
  no_reference_range: 'No reference range on file to sanity-check this value',
  low_confidence: 'Low confidence',
  missing_value: 'No result value was found',
}

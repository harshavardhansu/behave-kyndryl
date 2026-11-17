import type { Session } from '../types'

let csrfToken = ''

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function setSession(session: Session | null) {
  csrfToken = session?.csrf ?? ''
}

export async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET')
    headers.set('X-CSRF-Token', csrfToken)
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers,
      credentials: 'same-origin',
    })
  } catch {
    throw new ApiError(
      'The API is unavailable. Check that the local backend is running, then retry.',
      0
    )
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(
      typeof body?.detail === 'string'
        ? body.detail
        : `The request failed (${response.status}). No successful outcome is implied.`,
      response.status
    )
  }
  return response.json() as Promise<T>
}

export interface ProbeResult {
  status: number
  ok: boolean
  ms: number
  contentType: string
  preview: string
}

/** Calls an API endpoint and reports what came back (status, time, body) instead of throwing. Used by the API reference. */
export async function probe(
  path: string,
  init: { method: string; json?: unknown; form?: FormData }
): Promise<ProbeResult> {
  const headers = new Headers()
  let body: BodyInit | undefined
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(init.json)
  }
  if (init.form) body = init.form
  if (init.method !== 'GET') {
    headers.set('X-CSRF-Token', csrfToken)
    headers.set('Idempotency-Key', crypto.randomUUID())
  }
  const started = performance.now()
  try {
    const response = await fetch(`/api/v1${path}`, { method: init.method, headers, body, credentials: 'same-origin' })
    const contentType = response.headers.get('content-type') ?? ''
    let preview: string
    if (contentType.includes('json')) preview = JSON.stringify(await response.json(), null, 2)
    else if (contentType.startsWith('text/')) preview = await response.text()
    else {
      const blob = await response.blob()
      preview = `${contentType || 'Binary content'} · ${blob.size.toLocaleString()} bytes`
    }
    return { status: response.status, ok: response.ok, ms: Math.round(performance.now() - started), contentType, preview }
  } catch {
    return { status: 0, ok: false, ms: Math.round(performance.now() - started), contentType: '', preview: 'The API could not be reached.' }
  }
}

export function post<T>(path: string, payload: unknown, idempotent = false) {
  return request<T>(path, {
    method: 'POST',
    body: JSON.stringify(payload),
    headers: idempotent
      ? { 'Idempotency-Key': crypto.randomUUID() }
      : undefined,
  })
}

export async function downloadReport(
  format: 'json' | 'csv',
  incidentId = '',
  environment = 'All environments'
) {
  const response = await fetch('/api/v1/reports/export', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
    body: JSON.stringify({ format, incidentId, environment }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new ApiError(
      error?.detail ?? 'The report could not be exported.',
      response.status
    )
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `Behave-Kyndryl-${incidentId || 'workspace'}.${format}`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function downloadBlob(
  path: string,
  options: RequestInit = {}
): Promise<Blob> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET')
    headers.set('X-CSRF-Token', csrfToken)
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: 'same-origin',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new ApiError(
      error?.detail ?? `Failed to download file (${response.status})`,
      response.status
    )
  }
  return response.blob()
}

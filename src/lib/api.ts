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
  anchor.download = `BEHAVE KYNDRYL-${incidentId || 'workspace'}.${format}`
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

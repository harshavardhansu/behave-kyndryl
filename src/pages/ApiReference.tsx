import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Copy, ExternalLink, FileCode2, Play, Search, Server, ShieldAlert } from 'lucide-react'
import { Badge, Button, Notice, PageHeader } from '../components/ui'
import { probe, type ProbeResult } from '../lib/api'
import { useWorkspace } from '../context'
import './api-reference.css'

/**
 * What running an endpoint does to the workspace:
 * read: nothing changes · audit: only an audit-trail entry is added · write: creates real records (asks first)
 * destructive: not runnable from this page.
 */
type Effect = 'read' | 'audit' | 'write' | 'destructive'

interface Endpoint {
  method: 'GET' | 'POST'
  path: string
  title: string
  category: string
  description: string
  permission: string
  effect: Effect
  /** What a "write" run changes, shown before it runs. */
  consequence?: string
  json?: (incidentId: string) => unknown
  upload?: boolean
}

const SAMPLE_LOG = `2026-11-17T09:12:03Z ERROR checkout-svc request_id=req-api-reference
TimeoutError: connection pool exhausted after 30000 ms
    at Pool.acquire (/srv/checkout/db/pool.js:118:13)
`

const ENDPOINTS: Endpoint[] = [
  { method: 'GET', path: '/health', title: 'Service health', category: 'System', permission: 'public', effect: 'read',
    description: 'Database status, operating mode and workspace kind. The only route that is open without signing in.' },
  { method: 'GET', path: '/auth/session', title: 'Current session', category: 'System', permission: 'signed in', effect: 'read',
    description: 'The signed-in person, their role, permissions and the CSRF token used for every write.' },
  { method: 'GET', path: '/workspace', title: 'Workspace snapshot', category: 'System', permission: 'read', effect: 'read',
    description: 'Everything the screens show: incidents, missions, evidence, approvals, knowledge and integration status.' },
  { method: 'GET', path: '/foundry/agents', title: 'Foundry agents', category: 'Agents', permission: 'read', effect: 'read',
    description: 'Which of the 14 agent roles exist in Azure AI Foundry, their versions, and the mode missions run in.' },
  { method: 'GET', path: '/gateway', title: 'Tool Gateway log', category: 'Governance', permission: 'read', effect: 'read',
    description: 'Every outside action the agents asked for, who approved it, and whether it ran, was refused or failed.' },
  { method: 'GET', path: '/incidents/{incident_id}/readiness', title: 'Incident readiness', category: 'Incidents', permission: 'read', effect: 'read',
    description: 'Whether the incident has enough evidence and code for a mission, and what is still missing.' },
  { method: 'GET', path: '/incidents/{incident_id}/dependencies', title: 'Code dependencies', category: 'Incidents', permission: 'read', effect: 'read',
    description: 'Packages found in the code attached to the incident, read from its manifests.' },
  { method: 'GET', path: '/incidents/{incident_id}/source', title: 'Attached source', category: 'Incidents', permission: 'read', effect: 'read',
    description: 'The code connected to the incident: uploaded files, a project ZIP or a GitHub repository.' },
  { method: 'GET', path: '/incidents/{incident_id}/resolution-report', title: 'Resolution report (data)', category: 'Reports', permission: 'read', effect: 'read',
    description: 'The incident report as structured data: timeline, evidence, tool calls, decisions and outcome.' },
  { method: 'GET', path: '/incidents/{incident_id}/resolution-report/pdf', title: 'Resolution report (PDF)', category: 'Reports', permission: 'read', effect: 'read',
    description: 'The same report as a shareable PDF document.' },
  { method: 'GET', path: '/github/repositories', title: 'Connected repositories', category: 'Projects', permission: 'read', effect: 'read',
    description: 'GitHub repositories this workspace can read, as configured by the administrator.' },
  { method: 'POST', path: '/reports/export', title: 'Export records', category: 'Reports', permission: 'export', effect: 'audit',
    description: 'Exports the incident records as JSON. Adds an audit entry; nothing else changes.',
    json: (incidentId) => ({ format: 'json', incidentId, environment: 'All environments' }) },
  { method: 'POST', path: '/repositories/github-analysis', title: 'Analyse a repository file', category: 'Projects', permission: 'workflow:run', effect: 'audit',
    description: 'Reviews one file for security, architecture, workflow and reliability issues. Adds an audit entry; nothing else changes.',
    json: () => ({
      fileName: 'ci-pipeline.yml',
      repoName: 'example/checkout-api',
      content: 'name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n    - uses: actions/checkout@master\n    - run: echo key=$SECRET_KEY\n',
      scope: ['architecture', 'security', 'workflow', 'reliability'],
    }) },
  { method: 'POST', path: '/incidents', title: 'Create an incident', category: 'Incidents', permission: 'incident:create', effect: 'write',
    consequence: 'creates a new incident in this workspace, visible to everyone',
    description: 'Registers an incident with severity, environment, affected service and business impact.',
    json: () => ({
      title: 'API reference test: checkout pool saturation',
      description: 'Created from the API reference page to test the endpoint. Safe to close.',
      severity: 'Low',
      environment: 'Production',
      service: 'checkout-svc',
      impact: 'None: this is a test record created from the API reference.',
      source: 'Manual report',
      detectedAt: new Date(Date.now() - 60_000).toISOString(),
    }) },
  { method: 'POST', path: '/incidents/{incident_id}/evidence/upload', title: 'Attach a log file', category: 'Incidents', permission: 'evidence:add', effect: 'write', upload: true,
    consequence: 'attaches a small sample log file to the selected incident',
    description: 'Uploads a diagnostic file (.log, .txt, .json, .csv, .yml and source files). It is checked, redacted and grouped into errors.' },
  { method: 'POST', path: '/incidents/{incident_id}/missions', title: 'Start an agent mission', category: 'Agents', permission: 'workflow:run', effect: 'write',
    consequence: 'starts a real agent mission on the selected incident (Azure AI Foundry calls count against the daily budget)',
    description: 'The Orchestrator proposes a team for the incident; people then approve the team, the root cause, the fix and the outcome.' },
  { method: 'POST', path: '/admin/demo-reset', title: 'Reset the workspace', category: 'Administration', permission: 'admin:write', effect: 'destructive',
    description: 'Clears the workspace after writing a backup. Run it from Administration, where it asks for confirmation.' },
]

const EFFECT_LABEL: Record<Effect, string> = {
  read: 'Read only',
  audit: 'Adds an audit entry',
  write: 'Changes records',
  destructive: 'Destructive',
}

export function ApiReference() {
  const { data, session, selectedIncidentId, can, notify } = useWorkspace()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('All')
  const [incidentId, setIncidentId] = useState(selectedIncidentId || data.incidents[0]?.id || '')
  const [results, setResults] = useState<Record<string, ProbeResult & { url: string }>>({})
  const [running, setRunning] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)

  const categories = ['All', ...Array.from(new Set(ENDPOINTS.map((endpoint) => endpoint.category)))]
  const needle = search.trim().toLowerCase()
  const shown = ENDPOINTS.filter((endpoint) =>
    (category === 'All' || endpoint.category === category) &&
    (!needle || `${endpoint.method} ${endpoint.path} ${endpoint.title} ${endpoint.description}`.toLowerCase().includes(needle)))
  const keyOf = (endpoint: Endpoint) => `${endpoint.method} ${endpoint.path}`
  const resolve = (endpoint: Endpoint) => endpoint.path.replace('{incident_id}', encodeURIComponent(incidentId))
  const needsIncident = (endpoint: Endpoint) => endpoint.path.includes('{incident_id}')

  async function run(endpoint: Endpoint) {
    const key = keyOf(endpoint)
    setConfirming(null)
    setRunning(key)
    const path = resolve(endpoint)
    let form: FormData | undefined
    if (endpoint.upload) {
      form = new FormData()
      form.append('file', new Blob([SAMPLE_LOG], { type: 'text/plain' }), 'api-reference-sample.log')
    }
    const result = await probe(path, { method: endpoint.method, json: endpoint.json?.(incidentId), form })
    setResults((current) => ({ ...current, [key]: { ...result, url: `/api/v1${path}` } }))
    setRunning(null)
    if (result.ok && endpoint.effect === 'write') notify(`${endpoint.title}: done (HTTP ${result.status}).`)
  }

  function curl(endpoint: Endpoint) {
    const url = `${window.location.origin}/api/v1${resolve(endpoint)}`
    const lines = [`curl -X ${endpoint.method} "${url}"`, '  -b "<your signed-in session cookies>"']
    if (endpoint.method !== 'GET') lines.push('  -H "X-CSRF-Token: <csrf from GET /api/v1/auth/session>"')
    if (endpoint.json) lines.push('  -H "Content-Type: application/json"', `  -d '${JSON.stringify(endpoint.json(incidentId))}'`)
    if (endpoint.upload) lines.push('  -F "file=@your-error.log"')
    void navigator.clipboard.writeText(lines.join(' \\\n'))
    notify('cURL command copied.')
  }

  return (
    <div className="page-enter api-reference">
      <PageHeader
        title="API reference"
        description="The REST API behind every screen · versioned under /api/v1 · same sign-in and roles as the app"
        actions={
          <>
            <a href="/api/docs" target="_blank" rel="noreferrer" className="button button-secondary"><Server size={15} />Swagger UI<ExternalLink size={13} /></a>
            <a href="/api/openapi.json" target="_blank" rel="noreferrer" className="button button-secondary"><FileCode2 size={15} />OpenAPI JSON<ExternalLink size={13} /></a>
          </>
        }
      />

      <Notice title={`Requests run as ${session.user.name} (${session.user.role})`}>
        Read-only endpoints run directly. Endpoints that change records ask first and say what they will change. Results show the real status code, time and response.
      </Notice>

      <div className="api-toolbar">
        <label className="api-search">
          <Search size={15} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search endpoints" aria-label="Search endpoints" />
        </label>
        <label className="api-incident">
          Incident for <code>{'{incident_id}'}</code>
          <select value={incidentId} onChange={(event) => setIncidentId(event.target.value)} aria-label="Incident used for {incident_id}">
            {data.incidents.length === 0 && <option value="">No incidents yet</option>}
            {data.incidents.map((incident) => <option key={incident.id} value={incident.id}>{incident.id} · {incident.title}</option>)}
          </select>
        </label>
      </div>
      <div className="api-categories" role="group" aria-label="Filter by category">
        {categories.map((item) => (
          <button key={item} type="button" aria-pressed={category === item} onClick={() => setCategory(item)}>{item}</button>
        ))}
      </div>

      <div className="api-list">
        {shown.map((endpoint) => {
          const key = keyOf(endpoint)
          const result = results[key]
          const blockedByIncident = needsIncident(endpoint) && !incidentId
          const allowed = endpoint.permission === 'public' || endpoint.permission === 'signed in' || can(endpoint.permission)
          return (
            <article key={key} className="api-endpoint">
              <header>
                <span className={`api-method is-${endpoint.method.toLowerCase()}`}>{endpoint.method}</span>
                <code className="api-path">/api/v1{endpoint.path}</code>
                <span className={`api-effect is-${endpoint.effect}`}>{EFFECT_LABEL[endpoint.effect]}</span>
              </header>
              <h3>{endpoint.title}</h3>
              <p>{endpoint.description}</p>
              <div className="api-meta">
                <Badge tone="outline" dot={false}>{endpoint.category}</Badge>
                <span>Permission: <code>{endpoint.permission}</code>{!allowed && ' · your role does not have it, so expect HTTP 403'}</span>
              </div>
              {endpoint.json && (
                <details className="api-body">
                  <summary>Request body</summary>
                  <pre>{JSON.stringify(endpoint.json(incidentId), null, 2)}</pre>
                </details>
              )}
              <div className="api-actions">
                {endpoint.effect === 'destructive' ? (
                  <span className="api-guarded"><ShieldAlert size={14} /> Not run from this page. <Link to="/administration">Open Administration</Link></span>
                ) : confirming === key ? (
                  <span className="api-confirm" role="alert">
                    This {endpoint.consequence}. Run it?
                    <Button variant="primary" onClick={() => void run(endpoint)}>Yes, run it</Button>
                    <Button onClick={() => setConfirming(null)}>Cancel</Button>
                  </span>
                ) : (
                  <Button
                    variant="primary"
                    disabled={running === key || blockedByIncident}
                    onClick={() => (endpoint.effect === 'write' ? setConfirming(key) : void run(endpoint))}
                  >
                    <Play size={13} />
                    {running === key ? 'Running…' : 'Test live'}
                  </Button>
                )}
                <Button onClick={() => curl(endpoint)}><Copy size={13} />Copy cURL</Button>
                {blockedByIncident && <span className="api-hint">Create an incident first; this endpoint needs one.</span>}
              </div>
              {result && (
                <div className={`api-result ${result.ok ? 'is-ok' : 'is-error'}`}>
                  <div className="api-result-head">
                    <strong>HTTP {result.status || '—'}</strong>
                    <span>{result.ms} ms</span>
                    <code>{endpoint.method} {result.url}</code>
                    <button type="button" className="text-link" onClick={() => setResults((current) => { const next = { ...current }; delete next[key]; return next })}>Dismiss</button>
                  </div>
                  <pre>{result.preview.length > 6000 ? `${result.preview.slice(0, 6000)}\n… (${(result.preview.length - 6000).toLocaleString()} more characters)` : result.preview}</pre>
                </div>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}

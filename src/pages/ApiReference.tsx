import { useState } from 'react'
import {
  Copy,
  ExternalLink,
  FileCode2,
  Play,
  Search,
  Server,
} from 'lucide-react'
import { Badge, Button, Notice, PageHeader } from '../components/ui'
import { request } from '../lib/api'
import { useWorkspace } from '../context'

interface Endpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  title: string
  category: string
  description: string
  permission: string
  sampleBody?: string
}

const ENDPOINTS: Endpoint[] = [
  {
    method: 'GET',
    path: '/api/v1/foundry/agents',
    title: 'List 14 Azure AI Foundry Agents',
    category: '14 Foundry Agents & Intelligence',
    description: 'Retrieves all 14 Azure AI Foundry specialized agents, system prompts, squad phases, and human approval boundaries.',
    permission: 'read',
  },
  {
    method: 'POST',
    path: '/api/v1/incidents',
    title: 'Create Incident',
    category: 'Incident Management',
    description: 'Registers a new incident with severity, affected service, business impact, and environment.',
    permission: 'incident:create',
    sampleBody: JSON.stringify(
      {
        title: 'Checkout database connection pool saturation',
        description: 'HTTP 503 error spikes observed on the checkout endpoint under peak load.',
        severity: 'High',
        environment: 'Production',
        service: 'checkout-svc',
        impact: '15% of checkout transactions failing; customer orders blocked.',
        source: 'Monitoring alert',
        detectedAt: new Date().toISOString(),
      },
      null,
      2
    ),
  },
  {
    method: 'POST',
    path: '/api/v1/incidents/{id}/evidence/upload',
    title: 'Attach Error Log or Diagnostic File',
    category: 'Evidence & Diagnostics',
    description: 'Uploads and attaches a diagnostic file (.log, .txt, .json, .csv, .yml, .py, .java) to an incident for agent forensic analysis.',
    permission: 'evidence:add',
  },
  {
    method: 'GET',
    path: '/api/v1/incidents/{id}/resolution-report',
    title: 'Get Incident Resolution & Error Verification Report',
    category: 'Reports & Verification',
    description: 'Generates an authoritative Post-Incident Review (PIR) report verifying if attached error files are resolved.',
    permission: 'read',
  },
  {
    method: 'POST',
    path: '/api/v1/repositories/github-analysis',
    title: 'GitHub Repository Deep Analysis',
    category: 'Repository & Code Forensics',
    description: 'Performs multi-agent static and architectural analysis on GitHub repository files across Security, Architecture, Workflow, and Reliability.',
    permission: 'workflow:run',
    sampleBody: JSON.stringify(
      {
        fileName: 'ci-pipeline.yml',
        repoName: 'kyndryl-commerce/checkout-api',
        content: 'name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n    - uses: actions/checkout@master\n    - run: echo key=$SECRET_KEY\n',
        scope: ['architecture', 'security', 'workflow', 'reliability'],
      },
      null,
      2
    ),
  },
  {
    method: 'POST',
    path: '/api/v1/incidents/{id}/missions',
    title: 'Start 14-Agent AI Mission',
    category: '14 Foundry Agents & Intelligence',
    description: 'Activates the OpenAI Central Brain to orchestrate the 14 Azure AI Foundry specialized agents on the incident.',
    permission: 'workflow:run',
  },
  {
    method: 'GET',
    path: '/api/v1/workspace',
    title: 'Get Workspace State',
    category: 'System & Health',
    description: 'Fetches the current workspace snapshot, incidents, service topology, agents, and metrics.',
    permission: 'read',
  },
  {
    method: 'GET',
    path: '/api/v1/health',
    title: 'Service Health & AI Configuration',
    category: 'System & Health',
    description: 'Checks backend database connection, Azure OpenAI endpoint connectivity, and operational mode.',
    permission: 'public',
  },
  {
    method: 'POST',
    path: '/api/v1/admin/demo-reset',
    title: 'Workspace Reset / Clean Slate',
    category: 'Administration',
    description: 'Clears all demo activities for a fresh workspace (mode: "fresh") or restores demo stories (mode: "demo").',
    permission: 'admin:write',
    sampleBody: JSON.stringify({ mode: 'fresh' }, null, 2),
  },
]

export function ApiReference() {
  const { session, notify } = useWorkspace()
  const [search, setSearch] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('All categories')
  const [testingPath, setTestingPath] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<any>(null)
  const [copiedPath, setCopiedPath] = useState<string | null>(null)

  const categories = ['All categories', ...Array.from(new Set(ENDPOINTS.map((e) => e.category)))]

  const filtered = ENDPOINTS.filter((endpoint) => {
    const matchesCategory = selectedCategory === 'All categories' || endpoint.category === selectedCategory
    const matchesSearch =
      endpoint.path.toLowerCase().includes(search.toLowerCase()) ||
      endpoint.title.toLowerCase().includes(search.toLowerCase()) ||
      endpoint.description.toLowerCase().includes(search.toLowerCase())
    return matchesCategory && matchesSearch
  })

  async function testEndpoint(endpoint: Endpoint) {
    let url = endpoint.path
    if (url.includes('{id}')) {
      url = url.replace('{id}', 'INC-1042')
    }
    setTestingPath(endpoint.path)
    setTestResult(null)
    try {
      const res = await request<any>(url, {
        method: endpoint.method,
        body: endpoint.sampleBody && endpoint.method !== 'GET' ? endpoint.sampleBody : undefined,
      })
      setTestResult({ status: 'success', data: res })
      notify(`HTTP 200 OK — ${endpoint.path} succeeded!`)
    } catch (err: any) {
      setTestResult({ status: 'error', data: err?.message || 'Request failed' })
    }
  }

  function copyCurl(endpoint: Endpoint) {
    const curl = `curl -X ${endpoint.method} "http://127.0.0.1:8000${endpoint.path}" \\
  -H "Content-Type: application/json" \\
  -H "X-CSRF-Token: ${session.csrf || 'YOUR_CSRF_TOKEN'}" ${endpoint.sampleBody ? `\\\n  -d '${endpoint.sampleBody.replace(/\n/g, '')}'` : ''}`
    navigator.clipboard.writeText(curl)
    setCopiedPath(endpoint.path)
    setTimeout(() => setCopiedPath(null), 2000)
    notify('cURL command copied to clipboard!')
  }

  return (
    <div className="page-enter" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <PageHeader
        title="Behave Kyndryl API Reference"
        description="Production-grade RESTful interface / 14-Agent Intelligent AI Architecture"
        actions={
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <a
              href="/api/openapi.json"
              target="_blank"
              rel="noreferrer"
              className="button button-secondary"
            >
              <FileCode2 size={15} />
              OpenAPI JSON
              <ExternalLink size={13} />
            </a>
            <a
              href="/api/docs"
              target="_blank"
              rel="noreferrer"
              className="button button-secondary"
            >
              <Server size={15} />
              Swagger UI
              <ExternalLink size={13} />
            </a>
          </div>
        }
      />

      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
          <Search size={15} style={{ position: 'absolute', left: '10px', top: '11px', color: 'var(--color-muted, #a0aec0)' }} />
          <input
            style={{ width: '100%', paddingLeft: '32px' }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search endpoints by path, description, or action..."
          />
        </div>
        <div style={{ display: 'flex', gap: '0.35rem', overflowX: 'auto' }}>
          {categories.map((cat) => (
            <button
              key={cat}
              className={`button button-sm ${selectedCategory === cat ? 'button-primary' : 'button-secondary'}`}
              onClick={() => setSelectedCategory(cat)}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      <Notice title="Authenticated Enterprise Execution">
        All operational requests are authenticated using session credentials with active Role-Based Access Control (RBAC). Current role: <strong>{session.user.role}</strong> ({session.user.name}).
      </Notice>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {filtered.map((ep) => (
          <div
            key={`${ep.method}-${ep.path}`}
            style={{
              background: 'var(--color-surface, #1e2530)',
              border: '1px solid var(--color-border, #2d3748)',
              borderRadius: '8px',
              padding: '1.25rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.75rem',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                <span
                  style={{
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontWeight: 700,
                    fontSize: '11px',
                    fontFamily: 'monospace',
                    background:
                      ep.method === 'GET'
                        ? 'rgba(49, 130, 206, 0.25)'
                        : ep.method === 'POST'
                        ? 'rgba(56, 161, 105, 0.25)'
                        : ep.method === 'PUT'
                        ? 'rgba(214, 158, 46, 0.25)'
                        : 'rgba(229, 62, 62, 0.25)',
                    color:
                      ep.method === 'GET'
                        ? '#63b3ed'
                        : ep.method === 'POST'
                        ? '#68d391'
                        : ep.method === 'PUT'
                        ? '#f6e05e'
                        : '#fc8181',
                  }}
                >
                  {ep.method}
                </span>
                <span className="mono" style={{ fontSize: '14px', fontWeight: 600 }}>{ep.path}</span>
                <Badge tone="outline">{ep.category}</Badge>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', color: 'var(--color-muted, #a0aec0)' }}>
                  Permission: <strong className="mono">{ep.permission}</strong>
                </span>
                <Button onClick={() => copyCurl(ep)}>
                  <Copy size={13} />
                  {copiedPath === ep.path ? 'Copied!' : 'Copy cURL'}
                </Button>
                <Button variant="primary" onClick={() => void testEndpoint(ep)}>
                  <Play size={13} />
                  Test live
                </Button>
              </div>
            </div>

            <div style={{ fontSize: '13.5px', color: '#e2e8f0' }}>{ep.description}</div>

            {ep.sampleBody && (
              <div>
                <span style={{ fontSize: '11px', color: 'var(--color-muted, #a0aec0)', textTransform: 'uppercase', fontWeight: 600 }}>
                  Request Payload Example
                </span>
                <pre
                  style={{
                    marginTop: '4px',
                    padding: '0.5rem 0.75rem',
                    background: 'rgba(0,0,0,0.35)',
                    borderRadius: '6px',
                    fontFamily: 'monospace',
                    fontSize: '11.5px',
                    maxHeight: '130px',
                    overflowY: 'auto',
                    border: '1px solid var(--color-border, #2d3748)',
                  }}
                >
                  {ep.sampleBody}
                </pre>
              </div>
            )}

            {testingPath === ep.path && testResult && (
              <div
                style={{
                  marginTop: '0.5rem',
                  padding: '0.75rem',
                  background: 'rgba(0,0,0,0.5)',
                  border: `1px solid ${testResult.status === 'success' ? 'var(--color-success, #38a169)' : 'var(--color-danger, #e53e3e)'}`,
                  borderRadius: '6px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontSize: '12px' }}>
                  <strong style={{ color: testResult.status === 'success' ? '#68d391' : '#fc8181' }}>
                    {testResult.status === 'success' ? '✓ Response HTTP 200' : '✗ Response Error'}
                  </strong>
                  <button
                    className="text-link"
                    style={{ fontSize: '11px', cursor: 'pointer', background: 'none', border: 'none', color: 'inherit' }}
                    onClick={() => setTestResult(null)}
                  >
                    Dismiss
                  </button>
                </div>
                <pre style={{ margin: 0, fontSize: '11.5px', fontFamily: 'monospace', maxHeight: '180px', overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {JSON.stringify(testResult.data, null, 2)}
                </pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

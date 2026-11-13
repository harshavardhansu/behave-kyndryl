import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Check,
  FileJson2,
  FileUp,
  LockKeyhole,
  Plus,
  ShieldCheck,
  Upload,
  X,
} from 'lucide-react'
import { useWorkspace } from '../context'
import type { WorkflowAction } from '../context'
import { post, request } from '../lib/api'
import { environments, errorMessage, severities } from '../lib/format'
import type { Incident, IncidentInput } from '../types'
import { actionPermissions, GateList } from './incident'
import { Badge, Button, Modal, Notice, Select, Tabs } from './ui'

function localDateTime() {
  return new Date(Date.now() - new Date().getTimezoneOffset() * 60_000 - 60_000)
    .toISOString()
    .slice(0, 16)
}

function FilePicker({
  file,
  onFile,
  accept,
  onError,
}: {
  file: File | null
  onFile: (file: File | null) => void
  accept: string
  onError: (message: string) => void
}) {
  function choose(candidate?: File) {
    if (!candidate) return
    const extension = `.${candidate.name.split('.').pop()?.toLowerCase()}`
    if (!accept.split(',').includes(extension)) {
      onError(`Unsupported file type. Accepted: ${accept}`)
      return
    }
    if (candidate.size === 0 || candidate.size > 2 * 1024 * 1024) {
      onError('Choose a nonempty file no larger than 2 MB.')
      return
    }
    onError('')
    onFile(candidate)
  }
  return (
    <div
      className="file-drop-zone"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault()
        choose(event.dataTransfer.files[0])
      }}
    >
      <FileUp size={28} />
      <strong>{file ? file.name : 'Select an evidence file'}</strong>
      <span>
        {file
          ? `${(file.size / 1024).toFixed(1)} KB / ready to import`
          : `${accept.replaceAll(',', ' / ')} / UTF-8 / up to 2 MB`}
      </span>
      <label className="button button-secondary file-picker-label">
        <Upload size={15} />
        {file ? 'Choose another file' : 'Choose file'}
        <input
          type="file"
          aria-label="Choose evidence file"
          accept={accept}
          onChange={(event) => choose(event.target.files?.[0])}
        />
      </label>
      {file && (
        <button
          className="file-remove"
          aria-label="Remove selected file"
          onClick={() => onFile(null)}
        >
          <X size={15} />
        </button>
      )}
    </div>
  )
}

function CreateIncidentDialog() {
  const {
    data,
    environment,
    session,
    setCreateOpen,
    refresh,
    notify,
    selectIncident,
    can,
  } = useWorkspace()
  const navigate = useNavigate()
  const [tab, setTab] = useState('Create incident')
  const [form, setForm] = useState<IncidentInput>({
    title: '',
    description: '',
    severity: 'High',
    environment,
    service: 'checkout-svc',
    impact: '',
    source: 'Manual report',
    error: '',
    steps: '',
    expected: '',
    actual: '',
    correlationId: '',
    detectedAt: localDateTime(),
  })
  const [file, setFile] = useState<File | null>(null)
  const [errorFile, setErrorFile] = useState<File | null>(null)
  const [errorFileSnippet, setErrorFileSnippet] = useState<string>('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const update = (key: keyof IncidentInput, value: string) =>
    setForm((current) => ({ ...current, [key]: value }))

  function onDiagnosticFile(candidate: File | null) {
    setErrorFile(candidate)
    if (!candidate) {
      setErrorFileSnippet('')
      return
    }
    const reader = new FileReader()
    reader.onload = (e) => {
      const text = String(e.target?.result ?? '')
      setErrorFileSnippet(text.slice(0, 400))
      setForm((cur) => ({
        ...cur,
        error: cur.error || text.slice(0, 4000),
        source: cur.source === 'Manual report' ? 'Telemetry import' : cur.source,
      }))
    }
    reader.readAsText(candidate)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (tab === 'Import tickets') {
        if (!file) throw new Error('Choose a ticket JSON or CSV file.')
        const body = new FormData()
        body.append('file', file)
        const result = await request<{ message: string; ids: string[] }>(
          '/incidents/import',
          { method: 'POST', body }
        )
        await refresh()
        notify(result.message)
        setCreateOpen(false)
        navigate('/incidents')
      } else {
        const result = await post<Incident>('/incidents', {
          ...form,
          detectedAt: new Date(form.detectedAt).toISOString(),
        })
        if (errorFile) {
          try {
            const body = new FormData()
            body.append('file', errorFile)
            body.append('dataClassification', 'Internal')
            await request(`/incidents/${result.id}/evidence/upload`, {
              method: 'POST',
              body,
            })
          } catch (uploadErr) {
            console.warn('Diagnostic file attachment warning:', uploadErr)
          }
        }
        await refresh()
        selectIncident(result.id)
        setCreateOpen(false)
        navigate(`/incidents/${result.id}`)
        notify(
          errorFile
            ? `${result.id} created with attached error evidence (${errorFile.name}). Ready for investigation!`
            : `${result.id} created. Add evidence to begin an investigation.`
        )
      }
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onClose={() => !busy && setCreateOpen(false)}
      title="Create an incident"
      description={`${session.user.name} / ${session.user.role}`}
      wide
    >
      <form onSubmit={submit}>
        <div className="form-tabs">
          <Tabs
            items={['Create incident', 'Import tickets']}
            value={tab}
            onChange={setTab}
          />
        </div>
        <div className="modal-body form-body">
          {tab === 'Import tickets' ? (
            <>
              <FilePicker
                file={file}
                onFile={setFile}
                accept=".json,.csv"
                onError={setError}
              />
              <Notice title="Generic ticket import">
                Required fields: title, description, severity, environment,
                service, impact and detectedAt with a time zone. Up to 50
                records are validated atomically. No external ticketing
                connection is required.
              </Notice>
              <a className="text-link" href="/sample-tickets.json" download>
                <FileJson2 size={15} />
                Download sample ticket JSON
              </a>
            </>
          ) : (
            <>
              <label className="field-label">
                Issue title <span className="field-required">Required</span>
                <input
                  required
                  minLength={8}
                  maxLength={160}
                  placeholder="e.g. Checkout requests failing after release"
                  value={form.title}
                  onChange={(event) => update('title', event.target.value)}
                />
              </label>
              <div className="form-grid three">
                <label className="field-label">
                  Severity
                  <Select
                    label="Incident severity"
                    value={form.severity}
                    onChange={(event) => update('severity', event.target.value)}
                  >
                    {severities.map((severity) => (
                      <option key={severity}>{severity}</option>
                    ))}
                  </Select>
                </label>
                <label className="field-label">
                  Environment
                  <Select
                    label="Incident environment"
                    value={form.environment}
                    onChange={(event) =>
                      update('environment', event.target.value)
                    }
                  >
                    {environments.map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </Select>
                </label>
                <label className="field-label">
                  Affected service
                  <Select
                    label="Affected service"
                    value={form.service}
                    onChange={(event) => update('service', event.target.value)}
                  >
                    {data.services.map((service) => (
                      <option key={service.id} value={service.id}>
                        {service.name}
                      </option>
                    ))}
                    <option value="payment-api">Payment API sandbox</option>
                  </Select>
                </label>
              </div>
              <label className="field-label">
                Description <span className="field-required">Required</span>
                <textarea
                  rows={3}
                  required
                  minLength={20}
                  maxLength={8000}
                  value={form.description}
                  onChange={(event) =>
                    update('description', event.target.value)
                  }
                  placeholder="Observed symptoms, affected requests and relevant context"
                />
              </label>
              <label className="field-label">
                Business impact <span className="field-required">Required</span>
                <input
                  required
                  minLength={8}
                  maxLength={3000}
                  value={form.impact}
                  onChange={(event) => update('impact', event.target.value)}
                  placeholder="Customer impact, affected transactions or blocked delivery"
                />
              </label>
              <div className="field-group">
                <label className="field-label">
                  Attach error log or diagnostic file (Optional)
                  <span className="field-hint">
                    Attach an error file to automatically supply diagnostic context and evidence for AI agent analysis
                  </span>
                </label>
                <FilePicker
                  file={errorFile}
                  onFile={onDiagnosticFile}
                  accept=".txt,.log,.json,.csv,.yml,.yaml,.xml,.py,.java,.ts,.js,.sql,.md"
                  onError={setError}
                />
                {errorFileSnippet && (
                  <div
                    style={{
                      marginTop: '0.5rem',
                      padding: '0.5rem 0.75rem',
                      background: 'rgba(0,0,0,0.25)',
                      border: '1px solid var(--color-border, #2d3748)',
                      borderRadius: '6px',
                      fontSize: '11px',
                      fontFamily: 'monospace',
                      maxHeight: '120px',
                      overflowY: 'auto',
                    }}
                  >
                    <div style={{ color: 'var(--color-primary-light, #70a5ff)', fontWeight: 600, marginBottom: '4px' }}>
                      Extracted error preview from {errorFile?.name}:
                    </div>
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{errorFileSnippet}</pre>
                  </div>
                )}
              </div>
              <div className="form-grid">
                <label className="field-label">
                  Detection source
                  <Select
                    label="Detection source"
                    value={form.source}
                    onChange={(event) => update('source', event.target.value)}
                  >
                    {[
                      'Manual report',
                      'Monitoring alert',
                      'Repository analysis',
                      'Application testing',
                      'Telemetry import',
                    ].map((source) => (
                      <option key={source}>{source}</option>
                    ))}
                  </Select>
                </label>
                <label className="field-label">
                  First observed
                  <input
                    type="datetime-local"
                    required
                    value={form.detectedAt}
                    max={localDateTime()}
                    onChange={(event) =>
                      update('detectedAt', event.target.value)
                    }
                  />
                </label>
              </div>
              <details className="form-details">
                <summary>Diagnostic context & reproduction</summary>
                <div className="form-body">
                  <label className="field-label">
                    Error message
                    <textarea
                      value={form.error}
                      onChange={(event) => update('error', event.target.value)}
                      maxLength={6000}
                    />
                  </label>
                  <label className="field-label">
                    Steps to reproduce
                    <textarea
                      value={form.steps}
                      onChange={(event) => update('steps', event.target.value)}
                      maxLength={4000}
                    />
                  </label>
                  <div className="form-grid">
                    <label className="field-label">
                      Expected behavior
                      <textarea
                        value={form.expected}
                        onChange={(event) =>
                          update('expected', event.target.value)
                        }
                        maxLength={2000}
                      />
                    </label>
                    <label className="field-label">
                      Actual behavior
                      <textarea
                        value={form.actual}
                        onChange={(event) =>
                          update('actual', event.target.value)
                        }
                        maxLength={2000}
                      />
                    </label>
                  </div>
                  <label className="field-label">
                    Correlation or trace ID
                    <input
                      value={form.correlationId}
                      onChange={(event) =>
                        update('correlationId', event.target.value)
                      }
                      maxLength={200}
                    />
                  </label>
                </div>
              </details>
              {form.source !== 'Manual report' && (
                <Notice title="Manually supplied context">
                  The selected source is recorded as provenance. No monitoring,
                  repository or CI integration is contacted.
                </Notice>
              )}
              {!can('incident:create', form.environment) && (
                <Notice title="Environment permission required" tone="warning">
                  Your current role cannot create incidents in{' '}
                  {form.environment}.
                </Notice>
              )}
            </>
          )}
          {error && (
            <Notice title="Incident not created" tone="error">
              {error}
            </Notice>
          )}
        </div>
        <div className="modal-footer">
          <span className="form-footer-note">
            <LockKeyhole size={13} />
            Server-validated permissions
          </span>
          <Button onClick={() => setCreateOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            busy={busy}
            disabled={
              tab === 'Import tickets'
                ? !file
                : !can('incident:create', form.environment)
            }
          >
            <Plus size={18} />
            {tab === 'Import tickets' ? 'Import tickets' : 'Create incident'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function EvidenceDialog({ incidentId }: { incidentId: string }) {
  const { data, setEvidenceFor, refresh, notify } = useWorkspace()
  const incident = data.incidents.find((record) => record.id === incidentId)
  const [tab, setTab] = useState('Upload file')
  const [file, setFile] = useState<File | null>(null)
  const [form, setForm] = useState({
    title: '',
    type: 'Observation',
    source: '',
    classification: 'Unverified',
    excerpt: '',
    reason: '',
    timestamp: localDateTime(),
    traceId: '',
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const update = (key: string, value: string) =>
    setForm((current) => ({ ...current, [key]: value }))
  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (tab === 'Upload file') {
        if (!file) throw new Error('Choose a file before importing evidence.')
        const body = new FormData()
        body.append('file', file)
        await request(`/incidents/${incidentId}/evidence/upload`, {
          method: 'POST',
          body,
        })
      } else
        await post(`/incidents/${incidentId}/evidence`, {
          ...form,
          timestamp: new Date(form.timestamp).toISOString(),
        })
      await refresh()
      setEvidenceFor(null)
      notify(
        'Evidence attached with source provenance. Sensitive values are redacted before storage.'
      )
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal
      open
      onClose={() => !busy && setEvidenceFor(null)}
      title="Add investigation evidence"
      description={`${incidentId} / ${incident?.service ?? ''}`}
    >
      <form onSubmit={submit}>
        <div className="form-tabs">
          <Tabs
            items={['Upload file', 'Record observation']}
            value={tab}
            onChange={setTab}
          />
        </div>
        <div className="modal-body form-body">
          {tab === 'Upload file' ? (
            <>
              <FilePicker
                file={file}
                onFile={setFile}
                accept=".txt,.log,.json,.csv"
                onError={setError}
              />
              <Notice title="Untrusted evidence / no execution">
                Archives and executables are rejected. Structured log timestamps
                and source references are preserved. Uploaded content is not
                treated as an agent instruction.
              </Notice>
            </>
          ) : (
            <>
              <label className="field-label">
                Evidence title
                <input
                  required
                  minLength={5}
                  maxLength={180}
                  value={form.title}
                  onChange={(event) => update('title', event.target.value)}
                />
              </label>
              <div className="form-grid">
                <label className="field-label">
                  Type
                  <Select
                    label="Evidence type"
                    value={form.type}
                    onChange={(event) => update('type', event.target.value)}
                  >
                    {[
                      'Observation',
                      'Log',
                      'Metric',
                      'Trace',
                      'Change',
                      'Test',
                      'Document',
                    ].map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </Select>
                </label>
                <label className="field-label">
                  Classification
                  <Select
                    label="Evidence classification"
                    value={form.classification}
                    onChange={(event) =>
                      update('classification', event.target.value)
                    }
                  >
                    {['Unverified', 'Observed', 'Inferred'].map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </Select>
                </label>
              </div>
              <label className="field-label">
                Source reference
                <input
                  required
                  minLength={2}
                  maxLength={500}
                  value={form.source}
                  onChange={(event) => update('source', event.target.value)}
                  placeholder="Log location, report ID or source document"
                />
              </label>
              <label className="field-label">
                Observed timestamp
                <input
                  type="datetime-local"
                  required
                  value={form.timestamp}
                  onChange={(event) => update('timestamp', event.target.value)}
                />
              </label>
              <label className="field-label">
                Evidence excerpt
                <textarea
                  required
                  minLength={10}
                  maxLength={20000}
                  rows={5}
                  value={form.excerpt}
                  onChange={(event) => update('excerpt', event.target.value)}
                />
              </label>
              <label className="field-label">
                Why this evidence matters
                <textarea
                  maxLength={3000}
                  value={form.reason}
                  onChange={(event) => update('reason', event.target.value)}
                />
              </label>
              <label className="field-label">
                Trace ID
                <input
                  maxLength={200}
                  value={form.traceId}
                  onChange={(event) => update('traceId', event.target.value)}
                />
              </label>
            </>
          )}
          {error && (
            <Notice title="Evidence not attached" tone="error">
              {error}
            </Notice>
          )}
        </div>
        <div className="modal-footer">
          <Button disabled={busy} onClick={() => setEvidenceFor(null)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            type="submit"
            busy={busy}
            disabled={tab === 'Upload file' && !file}
          >
            <Upload size={18} />
            Attach evidence
          </Button>
        </div>
      </form>
    </Modal>
  )
}

const actionCopy: Record<
  WorkflowAction,
  { title: string; label: string; description: string }
> = {
  'start-investigation': {
    title: 'Start an investigation',
    label: 'Start investigation',
    description:
      'Replay the bounded synthetic workflow using linked evidence. Independent context tasks run in parallel phases. No model, repository or telemetry provider is contacted.',
  },
  pause: {
    title: 'Pause agent execution',
    label: 'Pause workflow',
    description:
      'The workflow will pause at its current checkpoint. Completed observations remain available.',
  },
  resume: {
    title: 'Resume the investigation',
    label: 'Resume workflow',
    description:
      'Continue the synthetic workflow from its persisted checkpoint with the same execution limits.',
  },
  cancel: {
    title: 'Cancel the active workflow',
    label: 'Cancel workflow',
    description:
      'Queued tasks will be cancelled. Evidence and execution history will remain in the audit trail.',
  },
  retry: {
    title: 'Retry a failed workflow',
    label: 'Retry workflow',
    description:
      'Retry only within the configured retry budget. Completed evidence is retained.',
  },
  'generate-fix': {
    title: 'Prepare a remediation proposal',
    label: 'Generate proposal',
    description:
      'Prepare a synthetic configuration diff for review. No repository is checked out, modified or executed.',
  },
  'run-validation': {
    title: 'Replay synthetic validation',
    label: 'Replay validation',
    description:
      'Record the pre-defined checkout validation fixture. These are synthetic results, not tests or scans executed against your software.',
  },
  'request-approval': {
    title: 'Request a separate human review',
    label: 'Request approval',
    description:
      'Mandatory gates must pass for the exact proposed commit. The requester cannot decide their own approval.',
  },
  approve: {
    title: 'Review & approve the change',
    label: 'Approve change',
    description:
      'Review the proposed diff, evidence, validation gates and rollback plan. This approval authorizes only the controlled demo workflow.',
  },
  reject: {
    title: 'Reject the proposed change',
    label: 'Reject change',
    description:
      'The change will return for revision. Record the evidence or requirement that prevents approval.',
  },
  deploy: {
    title: 'Authorize a simulated deployment',
    label: 'Simulate deployment',
    description:
      'No production system will be contacted. The local demo records the authorized release and requires a separate recovery-verification step.',
  },
  rollback: {
    title: 'Authorize a simulated rollback',
    label: 'Simulate rollback',
    description:
      'Record a simulated rollback to the previous approved artifact. The incident will reopen and prior approval readiness will be invalidated. No infrastructure is changed.',
  },
  verify: {
    title: 'Record recovery verification',
    label: 'Verify recovery',
    description:
      'Replay the synthetic 15-minute recovery window: error rate 0.2%, p95 latency 238 ms. This is not live monitoring.',
  },
  close: {
    title: 'Close the incident',
    label: 'Close incident',
    description:
      'Recovery evidence is required. The outcome will be recorded in the audit trail and captured as an unapproved knowledge draft.',
  },
  reopen: {
    title: 'Reopen the incident',
    label: 'Reopen incident',
    description:
      'Previous approval readiness and recovery status will be invalidated. Historical evidence remains available.',
  },
  assign: {
    title: 'Assign an incident commander',
    label: 'Assign commander',
    description:
      'The selected person becomes the incident owner and commander in this local workspace.',
  },
  escalate: {
    title: 'Escalate this incident',
    label: 'Escalate incident',
    description:
      'Severity will increase to Critical. The action is audited; no external paging integration is configured.',
  },
}

function ActionDialog({
  incidentId,
  action,
}: {
  incidentId: string
  action: WorkflowAction
}) {
  const { data, session, setActionDialog, runAction, actionPending, can } =
    useWorkspace()
  const [reason, setReason] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [owner, setOwner] = useState('Alex Morgan')
  const [error, setError] = useState('')
  const incident = data.incidents.find((record) => record.id === incidentId)
  const change = data.changes.find((record) => record.incidentId === incidentId)
  const copy = actionCopy[action]
  const needsReason = [
    'close',
    'reopen',
    'reject',
    'escalate',
    'rollback',
  ].includes(action)
  if (!incident) return null
  const permitted = can(actionPermissions[action], incident.environment)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      await runAction(incidentId, action, {
        reason,
        confirmation:
          action === 'approve' && reviewed ? 'APPROVE' : confirmation,
        owner,
      })
      setActionDialog(null)
    } catch (failure) {
      setError(errorMessage(failure))
    }
  }
  return (
    <Modal
      open
      onClose={() => !actionPending && setActionDialog(null)}
      title={copy.title}
      description={`${incidentId} / ${incident.environment}`}
    >
      <form onSubmit={submit}>
        <div className="modal-body form-body">
          <div className="detail-badges">
            <Badge>{incident.severity}</Badge>
            <Badge tone="outline">{incident.status}</Badge>
            <Badge tone="outline">{session.user.role}</Badge>
          </div>
          <Notice
            title={
              [
                'deploy',
                'rollback',
                'verify',
                'run-validation',
                'start-investigation',
              ].includes(action)
                ? 'Explicit demo operation'
                : 'Governed action'
            }
          >
            {copy.description}
          </Notice>
          {change &&
            ['approve', 'request-approval', 'deploy'].includes(action) && (
              <>
                <GateList gates={change.gates} />
                <h3>Rollback plan</h3>
                <p className="body-copy">{change.rollback}</p>
              </>
            )}
          {action === 'approve' && (
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={reviewed}
                onChange={(event) => setReviewed(event.target.checked)}
                required
              />
              <span>
                I reviewed the diff, evidence, quality gates and rollback plan.
              </span>
            </label>
          )}
          {['deploy', 'rollback'].includes(action) && (
            <label className="field-label">
              Type {incident.environment} to confirm the target environment
              <input
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                required
                autoComplete="off"
                placeholder={incident.environment}
              />
            </label>
          )}
          {action === 'assign' && (
            <label className="field-label">
              Incident commander
              <Select
                label="Incident commander"
                value={owner}
                onChange={(event) => setOwner(event.target.value)}
              >
                {[
                  'Alex Morgan',
                  'James Wilson',
                  'Maya Patel',
                  'Olivia Brooks',
                  'Noah Kim',
                ].map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </Select>
            </label>
          )}
          {needsReason && (
            <label className="field-label">
              {action === 'close' ? 'Verified outcome' : 'Decision reason'}
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                required
                minLength={action === 'close' ? 12 : 10}
                maxLength={3000}
                rows={4}
              />
            </label>
          )}
          {!permitted && (
            <Notice title="Insufficient permission" tone="warning">
              The current role does not have {actionPermissions[action]} for{' '}
              {incident.environment}. Select an authorized demo identity from
              your profile to review the applicable decision.
            </Notice>
          )}
          {error && (
            <Notice title="Action not completed" tone="error">
              {error}
            </Notice>
          )}
        </div>
        <div className="modal-footer">
          <Button
            disabled={actionPending}
            onClick={() => setActionDialog(null)}
          >
            Back
          </Button>
          <Button
            type="submit"
            variant="primary"
            busy={actionPending}
            disabled={
              !permitted ||
              (action === 'approve' && !reviewed) ||
              (['deploy', 'rollback'].includes(action) && confirmation !== incident.environment)
            }
          >
            {action === 'approve' ? (
              <ShieldCheck size={18} />
            ) : (
              <Check size={18} />
            )}
            {copy.label}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

export function WorkspaceDialogs() {
  const { createOpen, evidenceFor, actionDialog } = useWorkspace()
  return (
    <>
      {createOpen && <CreateIncidentDialog />}
      {evidenceFor && <EvidenceDialog incidentId={evidenceFor} />}
      {actionDialog && (
        <ActionDialog
          key={`${actionDialog.incidentId}-${actionDialog.action}`}
          {...actionDialog}
        />
      )}
    </>
  )
}

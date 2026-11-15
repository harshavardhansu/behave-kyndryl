import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Bug, CheckCheck, CircleAlert, FileCode2, Flame, Layers, Repeat2, Sparkles } from 'lucide-react'
import { useWorkspace } from '../context'
import { request } from '../lib/api'
import { dateTime, environments, errorMessage, severities, severityRank } from '../lib/format'
import type { ErrorIssue, ErrorSource } from '../types'
import { Badge, Button, DataTable, Drawer, KeyValue, Metric, Notice, PageHeader, Select } from '../components/ui'

const pad = (value: number) => value.toString().padStart(2, '0')
const DAY = 24 * 60 * 60 * 1000

/** How many occurrences each value of one field has, largest first. */
function breakdown(issues: ErrorIssue[], key: 'service' | 'environment' | 'category') {
  const totals = new Map<string, number>()
  for (const issue of issues) totals.set(issue[key], (totals.get(issue[key]) ?? 0) + issue.count)
  return [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6)
}

function Breakdown({ title, rows }: { title: string; rows: [string, number][] }) {
  const largest = Math.max(1, ...rows.map(([, total]) => total))
  return (
    <section className="error-breakdown" aria-label={title}>
      <h3>{title}</h3>
      {rows.length === 0 && <p className="error-breakdown-empty">Nothing recorded yet.</p>}
      {rows.map(([name, total]) => (
        <div key={name} className="error-bar">
          <span className="error-bar-name" title={name}>{name}</span>
          <span className="error-bar-track"><i style={{ width: `${(total / largest) * 100}%` }} /></span>
          <span className="error-bar-value">{total}</span>
        </div>
      ))}
    </section>
  )
}

/** Where the stack trace points in the connected source code, or why that cannot be said. */
function SourceLocation({ issue }: { issue: ErrorIssue }) {
  const query = useQuery({ queryKey: ['error-source', issue.id, issue.count], queryFn: () => request<ErrorSource>(`/errors/${issue.id}/source`) })
  if (query.isLoading) return <p className="body-copy">Looking for this error in the connected source code…</p>
  if (query.isError) return <Notice title="Source code could not be checked" tone="warning">{errorMessage(query.error)}</Notice>
  const located = query.data
  if (!located) return null
  return (
    <>
      {located.matches.map((match) => (
        <div key={`${match.path}:${match.line}`} className="error-source">
          <p className="error-source-path">
            <FileCode2 size={14} /> <code>{match.path}{match.line ? `:${match.line}` : ''}</code>
            {match.function && <span>in {match.function}</span>}
          </p>
          {match.snippet.length > 0 ? (
            <pre>
              {match.snippet.map((row) => (
                <span key={row.number} className={row.hit ? 'is-hit' : undefined}>
                  <b>{row.number}</b>{row.text || ' '}{'\n'}
                </span>
              ))}
            </pre>
          ) : (
            <p className="body-copy">{match.note}</p>
          )}
        </div>
      ))}
      {located.note && <Notice title="Exact location not established">{located.note}</Notice>}
      {located.matches.length > 0 && located.source && <p className="error-source-from">Read from {located.source}.</p>}
    </>
  )
}

export function Errors() {
  const { data, can, refresh, notify, selectIncident } = useWorkspace()
  const [params] = useSearchParams()
  const [severity, setSeverity] = useState('All severities')
  const [service, setService] = useState('All applications')
  const [environment, setEnvironment] = useState('All environments')
  const [category, setCategory] = useState('All types')
  const [status, setStatus] = useState('All statuses')
  const [selectedId, setSelectedId] = useState<string | null>(params.get('error'))
  const [busy, setBusy] = useState(false)
  const issues = useMemo(() => data.errors ?? [], [data.errors])
  const selected = issues.find((issue) => issue.id === selectedId)
  const open = issues.filter((issue) => issue.status === 'Open')
  const [cutoff] = useState(() => Date.now() - DAY)  // the workspace's snapshot date is fixed demo data, so use the real clock
  const rows = issues
    .filter(
      (issue) =>
        (severity === 'All severities' || issue.severity === severity) &&
        (service === 'All applications' || issue.service === service) &&
        (environment === 'All environments' || issue.environment === environment) &&
        (category === 'All types' || issue.category === category) &&
        (status === 'All statuses' || issue.status === status)
    )
    .sort((a, b) => severityRank[a.severity] - severityRank[b.severity] || b.lastSeen.localeCompare(a.lastSeen))

  async function setIssueStatus(issue: ErrorIssue, next: ErrorIssue['status']) {
    setBusy(true)
    try {
      await request(`/errors/${issue.id}`, { method: 'PATCH', body: JSON.stringify({ status: next, note: '' }) })
      await refresh()
      notify(`${issue.id} marked ${next.toLowerCase()}. The change is in the audit trail.`)
    } catch (failure) {
      notify(errorMessage(failure), true)
    } finally {
      setBusy(false)
    }
  }

  const columns: ColumnDef<ErrorIssue>[] = [
    {
      accessorKey: 'title',
      header: 'Error',
      cell: ({ row }) => (
        <div className="incident-cell">
          <span className="mono record-id">{row.original.id} / {row.original.type}</span>
          <strong>{row.original.title}</strong>
        </div>
      ),
    },
    { accessorKey: 'severity', header: 'Severity', cell: ({ getValue }) => <Badge>{String(getValue())}</Badge> },
    { accessorKey: 'count', header: 'Occurrences', cell: ({ getValue }) => <span className="mono table-mono">{String(getValue())}</span> },
    { accessorKey: 'service', header: 'Application', cell: ({ getValue }) => <span className="mono table-mono">{String(getValue())}</span> },
    { accessorKey: 'environment', header: 'Environment' },
    { accessorKey: 'category', header: 'Type' },
    { accessorKey: 'lastSeen', header: 'Last seen', cell: ({ row }) => (row.original.sample.timestampKnown ? dateTime(row.original.lastSeen) : `${dateTime(row.original.lastSeen)} (upload time)`) },
    { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <Badge>{String(getValue())}</Badge> },
  ]

  return (
    <div className="page-enter">
      <PageHeader
        title="Error tracking"
        description="Errors found in uploaded logs and stack traces / Grouped by fingerprint / Real records only"
      />
      <div className="metrics-grid four">
        <Metric label="Total errors" value={pad(issues.reduce((sum, issue) => sum + issue.count, 0))} detail="Occurrences across all uploaded logs" icon={Bug} />
        <Metric label="Open issues" value={pad(open.length)} detail="Distinct errors not yet resolved" icon={CircleAlert} critical={open.length > 0} />
        <Metric label="Resolved" value={pad(issues.filter((issue) => issue.status === 'Resolved').length)} detail="Marked resolved by a person" icon={CheckCheck} />
        <Metric label="Critical" value={pad(open.filter((issue) => issue.severity === 'Critical').length)} detail="Open, fatal or out-of-memory" icon={Flame} critical />
      </div>
      <div className="metrics-grid four">
        <Metric label="High priority" value={pad(open.filter((issue) => issue.severity === 'High').length)} detail="Open, with an exception" icon={Layers} />
        <Metric label="Recurring" value={pad(issues.filter((issue) => issue.count > 1).length)} detail="Seen more than once" icon={Repeat2} />
        <Metric label="New in 24 hours" value={pad(issues.filter((issue) => new Date(issue.createdAt).getTime() >= cutoff).length)} detail="First recorded in the last day" icon={Sparkles} />
        <Metric label="Located in code" value={pad(issues.filter((issue) => issue.frames.length > 0).length)} detail="Have a stack trace to follow" icon={FileCode2} />
      </div>
      {issues.length === 0 && (
        <Notice title="No errors recorded yet">
          This page fills from real uploads only. Create an incident and attach an error log (or paste a stack trace): every error in it is found, grouped with its
          repeats and listed here. Demo incidents that came with the workspace are not counted.
        </Notice>
      )}
      <div className="error-breakdowns">
        <Breakdown title="Errors by application" rows={breakdown(issues, 'service')} />
        <Breakdown title="Errors by environment" rows={breakdown(issues, 'environment')} />
        <Breakdown title="Errors by type" rows={breakdown(issues, 'category')} />
      </div>
      <DataTable
        data={rows}
        columns={columns}
        onRowClick={(issue) => setSelectedId(issue.id)}
        searchPlaceholder="Search error messages, types or applications"
        pageSize={8}
        toolbar={
          <>
            <Select label="Error severity filter" value={severity} onChange={(event) => setSeverity(event.target.value)}>
              <option>All severities</option>
              {severities.map((value) => <option key={value}>{value}</option>)}
            </Select>
            <Select label="Error application filter" value={service} onChange={(event) => setService(event.target.value)}>
              <option>All applications</option>
              {[...new Set(issues.map((issue) => issue.service))].sort().map((value) => <option key={value}>{value}</option>)}
            </Select>
            <Select label="Error environment filter" value={environment} onChange={(event) => setEnvironment(event.target.value)}>
              <option>All environments</option>
              {environments.map((value) => <option key={value}>{value}</option>)}
            </Select>
            <Select label="Error type filter" value={category} onChange={(event) => setCategory(event.target.value)}>
              <option>All types</option>
              {[...new Set(issues.map((issue) => issue.category))].sort().map((value) => <option key={value}>{value}</option>)}
            </Select>
            <Select label="Error status filter" value={status} onChange={(event) => setStatus(event.target.value)}>
              {['All statuses', 'Open', 'Resolved', 'Ignored'].map((value) => <option key={value}>{value}</option>)}
            </Select>
          </>
        }
        emptyTitle="No matching errors"
        emptyDescription="No recorded error matches these filters."
      />
      <Drawer open={Boolean(selected)} onClose={() => setSelectedId(null)} title={selected?.title ?? 'Error'} subtitle={selected ? `${selected.id} / fingerprint ${selected.fingerprint}` : undefined}>
        {selected && (
          <>
            <div className="detail-badges">
              <Badge>{selected.severity}</Badge>
              <Badge>{selected.status}</Badge>
              <Badge tone="outline">{selected.category}</Badge>
            </div>
            <p className="body-copy">{selected.message}</p>
            <dl>
              <KeyValue label="Error type" mono>{selected.type}</KeyValue>
              <KeyValue label="Application" mono>{selected.service}</KeyValue>
              <KeyValue label="Environment">{selected.environment}</KeyValue>
              <KeyValue label="Occurrences">{selected.count}</KeyValue>
              <KeyValue label="First seen">{dateTime(selected.firstSeen)}</KeyValue>
              <KeyValue label="Last seen">{dateTime(selected.lastSeen)}{selected.sample.timestampKnown ? '' : ' (the log had no timestamp: this is the upload time)'}</KeyValue>
              {selected.sample.requestId && <KeyValue label="Request ID" mono>{selected.sample.requestId}</KeyValue>}
              {selected.sample.correlationId && <KeyValue label="Correlation ID" mono>{selected.sample.correlationId}</KeyValue>}
              <KeyValue label="Linked incident">
                {selected.incidentIds.length
                  ? selected.incidentIds.map((id) => (
                    <Link key={id} to={`/incidents/${id}`} className="text-link" onClick={() => selectIncident(id)}>{id} </Link>
                  ))
                  : 'None'}
              </KeyValue>
            </dl>
            <h3 className="detail-section-title">Where it happens in the code</h3>
            <SourceLocation issue={selected} />
            <h3 className="detail-section-title">Stack trace from the log</h3>
            {selected.sample.stack.length ? <pre className="error-stack">{selected.sample.stack.join('\n')}</pre> : <p className="body-copy">The log has no stack trace for this error.</p>}
            <div className="error-actions">
              {selected.status !== 'Resolved' && <Button variant="primary" busy={busy} disabled={!can('incident:update', selected.environment)} onClick={() => void setIssueStatus(selected, 'Resolved')}>Mark resolved</Button>}
              {selected.status !== 'Ignored' && <Button busy={busy} disabled={!can('incident:update', selected.environment)} onClick={() => void setIssueStatus(selected, 'Ignored')}>Ignore</Button>}
              {selected.status !== 'Open' && <Button busy={busy} disabled={!can('incident:update', selected.environment)} onClick={() => void setIssueStatus(selected, 'Open')}>Reopen</Button>}
            </div>
            <p className="error-source-from">An error marked resolved reopens by itself if it is seen again in a later upload.</p>
          </>
        )}
      </Drawer>
    </div>
  )
}

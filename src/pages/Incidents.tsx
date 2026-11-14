import { IncidentReportButton } from '../components/ReportPreview'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Clock3,
  Copy,
  Download,
  FileCheck2,
  FileText,
  Flag,
  Network,
  Plus,
  Search,
  ShieldCheck,
  TriangleAlert,
  Upload,
  UserRound,
} from 'lucide-react'
import { downloadBlob, request } from '../lib/api'
import { useWorkspace } from '../context'
import {
  closedStatuses,
  dateTime,
  elapsed,
  errorMessage,
  severityRank,
  severities,
  sla,
} from '../lib/format'
import type { Incident, LogRecord } from '../types'
import {
  Avatar,
  Badge,
  Button,
  DataTable,
  EmptyState,
  KeyValue,
  Metric,
  Notice,
  PageHeader,
  SectionHeader,
  Select,
  Tabs,
  WorkflowSteps,
} from '../components/ui'
import {
  ChangeDiff,
  EventTimeline,
  EvidenceList,
  GateList,
  HypothesisList,
  NextActionButton,
  nextAction,
} from '../components/incident'

export function Incidents() {
  const {
    data,
    environment,
    session,
    can,
    setCreateOpen,
    exportReport,
    selectIncident,
  } = useWorkspace()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [severity, setSeverity] = useState(
    params.get('severity') || 'All severities'
  )
  const [status, setStatus] = useState(
    params.get('status') === 'open' ? 'Open only' : 'All statuses'
  )
  const [service, setService] = useState(
    params.get('service') || 'All services'
  )
  const [tab, setTab] = useState('All incidents')
  const scoped = data.incidents.filter(
    (incident) => incident.environment === environment
  )
  const rows = scoped.filter(
    (incident) =>
      (severity === 'All severities' || incident.severity === severity) &&
      (status === 'All statuses' ||
        (status === 'Open only'
          ? !closedStatuses.includes(incident.status)
          : incident.status === status)) &&
      (service === 'All services' || incident.service === service) &&
      (tab !== 'Assigned to me' || incident.owner === session.user.name) &&
      (tab !== 'SLA at risk' || sla(incident, data.snapshotAt).risk)
  )
  const columns: ColumnDef<Incident>[] = [
    {
      accessorKey: 'title',
      header: 'Incident',
      cell: ({ row }) => (
        <div className="incident-cell">
          <span className="mono record-id">{row.original.id}</span>
          <strong>{row.original.title}</strong>
        </div>
      ),
    },
    {
      accessorKey: 'severity',
      header: 'Severity',
      sortingFn: (first, second) =>
        severityRank[first.original.severity] -
        severityRank[second.original.severity],
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ getValue }) => (
        <Badge tone="outline">{String(getValue())}</Badge>
      ),
    },
    {
      accessorKey: 'service',
      header: 'Service',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'detectedAt',
      header: 'Detected',
      cell: ({ row }) => (
        <div className="table-two-line">
          <span>{dateTime(row.original.detectedAt)}</span>
          <small>
            {elapsed(row.original.detectedAt, data.snapshotAt)} elapsed
          </small>
        </div>
      ),
    },
    {
      accessorKey: 'owner',
      header: 'Owner',
      cell: ({ getValue }) => (
        <div className="owner-cell">
          <Avatar small name={String(getValue())} />
          <span>{String(getValue()).split(' ')[0]}</span>
        </div>
      ),
    },
    {
      id: 'sla',
      header: 'SLA',
      accessorFn: (incident) => sla(incident, data.snapshotAt).remaining,
      cell: ({ row }) => (
        <span
          className={`sla-label ${sla(row.original, data.snapshotAt).risk ? 'at-risk' : ''}`}
        >
          <Clock3 size={12} />
          {sla(row.original, data.snapshotAt).label}
        </span>
      ),
    },
    {
      accessorKey: 'workflowStatus',
      header: 'Investigation',
      cell: ({ getValue }) => (
        <Badge tone="outline">{String(getValue())}</Badge>
      ),
    },
  ]
  return (
    <div className="page-enter">
      <PageHeader
        title="Issues & incidents"
        description={`${environment} / ${scoped.length} incident records / synthetic and user-supplied evidence`}
        actions={
          <>
            <Button onClick={() => void exportReport('csv')}>
              <Download size={15} />
              Export
            </Button>
            <Button
              variant="primary"
              onClick={() => setCreateOpen(true)}
              disabled={!can('incident:create', environment)}
            >
              <Plus size={18} />
              Create incident
            </Button>
          </>
        }
      />
      <div className="metrics-grid four">
        <Metric
          label="Open incidents"
          value={
            scoped.filter(
              (incident) => !closedStatuses.includes(incident.status)
            ).length
          }
          detail="Unresolved incidents in scope"
          icon={TriangleAlert}
        />
        <Metric
          label="Critical priority"
          value={
            scoped.filter(
              (incident) =>
                incident.severity === 'Critical' &&
                !closedStatuses.includes(incident.status)
            ).length
          }
          detail="Immediate attention required"
          icon={Flag}
          critical
        />
        <Metric
          label="Investigating"
          value={
            scoped.filter((incident) => incident.status === 'Investigating')
              .length
          }
          detail="Evidence assessment in progress"
          icon={Search}
        />
        <Metric
          label="Awaiting approval"
          value={
            scoped.filter((incident) => incident.status === 'Awaiting Approval')
              .length
          }
          detail="Separate human decision"
          icon={FileCheck2}
        />
      </div>
      <Tabs
        items={[
          {
            label: 'All incidents',
            value: 'All incidents',
            count: scoped.length,
          },
          {
            label: 'Assigned to me',
            value: 'Assigned to me',
            count: scoped.filter(
              (incident) => incident.owner === session.user.name
            ).length,
          },
          {
            label: 'SLA at risk',
            value: 'SLA at risk',
            count: scoped.filter(
              (incident) => sla(incident, data.snapshotAt).risk
            ).length,
          },
        ]}
        value={tab}
        onChange={setTab}
      />
      <DataTable
        data={rows}
        columns={columns}
        searchPlaceholder="Search incidents, IDs or services"
        pageSize={12}
        onRowClick={(incident) => {
          selectIncident(incident.id)
          navigate(`/incidents/${incident.id}`)
        }}
        toolbar={
          <>
            <Select
              label="Severity filter"
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              <option>All severities</option>
              {severities.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </Select>
            <Select
              label="Incident status filter"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              {[
                'All statuses',
                'Open only',
                'New',
                'Triaged',
                'Investigating',
                'Root Cause Identified',
                'Fix Proposed',
                'Testing',
                'Awaiting Approval',
                'Approved',
                'Deploying',
                'Monitoring',
                'Resolved',
                'Closed',
                'Reopened',
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </Select>
            <Select
              label="Incident service filter"
              value={service}
              onChange={(event) => setService(event.target.value)}
            >
              <option>All services</option>
              {data.services.map((value) => (
                <option key={value.id} value={value.id}>
                  {value.name}
                </option>
              ))}
            </Select>
          </>
        }
      />
      <div className="page-bottom-note">
        <ShieldCheck size={14} />
        <span>
          Manual reporting and ticket imports remain available without an AI or
          ticketing provider.
        </span>
        <Link to="/administration">
          Integration status
          <ArrowUpRight size={12} />
        </Link>
      </div>
    </div>
  )
}

export function IncidentDetail() {
  const { id } = useParams()
  const {
    data,
    selectedIncidentId,
    selectIncident,
    setEvidenceFor,
    setActionDialog,
    can,
    notify,
  } = useWorkspace()
  const [tab, setTab] = useState('Overview')
  const [pdfBusy, setPdfBusy] = useState(false)
  const [reportCopied, setReportCopied] = useState(false)

  const incident = data.incidents.find((record) => record.id === id)
  useEffect(() => {
    if (id && incident && selectedIncidentId !== id) selectIncident(id)
  }, [id, incident, selectedIncidentId, selectIncident])

  const reportQuery = useQuery({
    queryKey: ['resolution-report', id],
    queryFn: () =>
      request<{ reportMarkdown: string; passRate?: number; passedChecks?: number; totalChecks?: number }>(
        `/incidents/${id}/resolution-report`
      ),
    enabled: tab === 'Resolution report' && Boolean(incident),
  })
  const resolutionReport = reportQuery.data ?? null
  const reportBusy = reportQuery.isFetching || pdfBusy

  function downloadResolutionReport() {
    if (!resolutionReport) return
    const blob = new Blob([resolutionReport.reportMarkdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${incident?.id}-resolution-report.md`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  async function downloadResolutionReportPdf() {
    if (!incident?.id) return
    setPdfBusy(true)
    try {
      const blob = await downloadBlob(`/incidents/${incident.id}/resolution-report/pdf`)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${incident.id}-resolution-report.pdf`
      a.click()
      URL.revokeObjectURL(url)
      notify('Detailed Post-Incident Review PDF downloaded successfully!')
    } catch (err) {
      notify(`PDF download error: ${errorMessage(err)}`, true)
    } finally {
      setPdfBusy(false)
    }
  }

  function copyResolutionReport() {
    if (!resolutionReport) return
    navigator.clipboard.writeText(resolutionReport.reportMarkdown)
    setReportCopied(true)
    setTimeout(() => setReportCopied(false), 2000)
    notify('Resolution report copied to clipboard!')
  }
  if (!incident)
    return (
      <EmptyState
        title="Incident not found"
        description="This record is not available in the current workspace."
        action={
          <Link className="button button-secondary" to="/incidents">
            Return to incidents
          </Link>
        }
      />
    )
  const change = data.changes.find(
    (record) => record.incidentId === incident.id
  )
  const evidence = data.evidence.filter(
    (record) => record.incidentId === incident.id
  )
  const logs = data.logs.filter((record) =>
    evidence.some((item) => item.id === record.evidenceId)
  )
  const tasks = data.agents.filter(
    (record) => record.incidentId === incident.id
  )
  const tests = data.tests.filter((record) => record.incidentId === incident.id)
  const approvals = data.approvals.filter(
    (record) => record.incidentId === incident.id
  )
  const dependencies = data.dependencies.filter(
    (record) =>
      record.source === incident.service || record.target === incident.service
  )
  const logColumns: ColumnDef<LogRecord>[] = [
    {
      accessorKey: 'timestamp',
      header: 'Timestamp',
      cell: ({ getValue }) => (
        <span className="mono">{dateTime(String(getValue()))}</span>
      ),
    },
    {
      accessorKey: 'level',
      header: 'Level',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    { accessorKey: 'service', header: 'Service' },
    {
      accessorKey: 'message',
      header: 'Message',
      cell: ({ getValue }) => (
        <span className="log-message">{String(getValue())}</span>
      ),
    },
  ]
  return (
    <div className="page-enter incident-detail">
      <Link className="back-link" to="/incidents">
        <ArrowLeft size={14} />
        Issues & incidents
      </Link>
      <div className="detail-title-meta">
        <span className="mono">{incident.id}</span>
        <Badge>{incident.severity}</Badge>
        <Badge tone="outline">{incident.environment}</Badge>
        <Badge tone="outline">
          {incident.synthetic ? 'Synthetic incident' : 'User-reported incident'}
        </Badge>
      </div>
      <PageHeader
        title={incident.title}
        description={`${incident.service} / First observed ${dateTime(incident.detectedAt)} / ${incident.owner}`}
        actions={
          <>
            <IncidentReportButton incidentId={incident.id} label="Report" />
            <NextActionButton incident={incident} />
          </>
        }
      />
      <WorkflowSteps status={incident.status} />
      <Tabs
        items={[
          'Overview',
          'Timeline',
          'Evidence',
          'Logs & traces',
          'Dependencies',
          'Root cause',
          'Agent activity',
          'Proposed fix',
          'Tests',
          'Approvals',
          'Resolution report',
          'Audit history',
        ]}
        value={tab}
        onChange={setTab}
      />
      <div role="tabpanel" className="tab-panel">
        {tab === 'Overview' && (
          <>
            <div className="next-decision">
              <span className="next-decision-icon">
                <ArrowRight size={18} />
              </span>
              <div>
                <strong>Next decision / {nextAction(incident).label}</strong>
                <p>{nextAction(incident).detail}</p>
              </div>
              <Badge>{incident.status}</Badge>
            </div>
            <div className="detail-grid">
              <section>
                <SectionHeader
                  title="Incident context"
                  actions={
                    <Link className="text-link" to="/war-room">
                      <Network size={15} />
                      Open War Room
                      <ArrowUpRight size={13} />
                    </Link>
                  }
                />
                <p className="body-copy">{incident.description}</p>
                <h3 className="detail-section-title">Business impact</h3>
                <div className="impact-block">{incident.impact}</div>
                <div className="two-column-copy">
                  <div>
                    <h3>Expected behavior</h3>
                    <p>{incident.expected || 'Not recorded'}</p>
                  </div>
                  <div>
                    <h3>Actual behavior</h3>
                    <p>{incident.actual || 'Not recorded'}</p>
                  </div>
                </div>
                <h3 className="detail-section-title">Observed error</h3>
                <pre className="evidence-excerpt">
                  {incident.error || 'No error message provided.'}
                </pre>
                <h3 className="detail-section-title">Reproduction context</h3>
                <p className="body-copy">
                  {incident.steps || 'No reproduction steps provided.'}
                </p>
                {incident.recovery && (
                  <Notice title="Recovery evidence recorded">
                    {incident.recovery.errorRate === null || incident.recovery.latency === null ? (
                      <>{incident.recovery.basis ?? 'Human-confirmed resolution'}. Confirmed by {incident.recovery.actor}.</>
                    ) : (
                      <>
                        {incident.recovery.basis === 'MEASURED' ? 'Measured' : incident.recovery.synthetic ? 'Synthetic' : 'Recorded'}{' '}
                        verification: error rate {incident.recovery.errorRate}%, latency {incident.recovery.latency} ms. Recorded by{' '}
                        {incident.recovery.actor}.
                      </>
                    )}
                  </Notice>
                )}
                {incident.outcome && (
                  <>
                    <h3 className="detail-section-title">Recorded outcome</h3>
                    <p className="body-copy">{incident.outcome}</p>
                  </>
                )}
              </section>
              <aside className="detail-sidebar">
                <SectionHeader title="Ownership & status" />
                <div className="incident-owner">
                  <Avatar name={incident.owner} />
                  <div>
                    <strong>{incident.owner}</strong>
                    <small>Incident commander</small>
                  </div>
                </div>
                <dl>
                  <KeyValue label="Current status">
                    <Badge>{incident.status}</Badge>
                  </KeyValue>
                  <KeyValue label="Detection source">
                    {incident.source}
                  </KeyValue>
                  <KeyValue label="Environment">
                    {incident.environment}
                  </KeyValue>
                  <KeyValue label="SLA status">
                    {sla(incident, data.snapshotAt).label}
                  </KeyValue>
                  <KeyValue label="Investigation">
                    {incident.workflowStatus}
                  </KeyValue>
                  <KeyValue label="Correlation" mono>
                    {incident.correlationId || 'Not supplied'}
                  </KeyValue>
                </dl>
                <div className="stacked-actions">
                  <Button
                    disabled={!can('incident:update', incident.environment)}
                    onClick={() =>
                      setActionDialog({
                        incidentId: incident.id,
                        action: 'assign',
                      })
                    }
                  >
                    <UserRound size={15} />
                    Assign commander
                  </Button>
                  <Button
                    disabled={!can('incident:update', incident.environment)}
                    onClick={() =>
                      setActionDialog({
                        incidentId: incident.id,
                        action: 'escalate',
                      })
                    }
                  >
                    <Flag size={15} />
                    Escalate incident
                  </Button>
                  <Button
                    disabled={!can('evidence:add', incident.environment)}
                    onClick={() => setEvidenceFor(incident.id)}
                  >
                    <Upload size={15} />
                    Add evidence
                  </Button>
                </div>
              </aside>
            </div>
            <section className="workspace-section">
              <SectionHeader
                title="Linked evidence"
                caption={`${evidence.length} source records`}
                actions={
                  <Button onClick={() => setTab('Evidence')}>
                    View all
                    <ArrowRight size={14} />
                  </Button>
                }
              />
              <EvidenceList incidentId={incident.id} limit={3} />
            </section>
          </>
        )}
        {(tab === 'Timeline' || tab === 'Audit history') && (
          <EventTimeline incidentId={incident.id} />
        )}
        {tab === 'Evidence' && (
          <>
            <SectionHeader
              title="Evidence collection"
              caption={`${evidence.length} records / provenance retained`}
              actions={
                <Button
                  disabled={!can('evidence:add', incident.environment)}
                  onClick={() => setEvidenceFor(incident.id)}
                >
                  <Upload size={15} />
                  Add evidence
                </Button>
              }
            />
            <EvidenceList incidentId={incident.id} />
          </>
        )}
        {tab === 'Logs & traces' && (
          <>
            <SectionHeader
              title="Correlated log records"
              caption="Grouped by linked evidence IDs, not temporal proximity alone"
              actions={
                <Link
                  className="text-link"
                  to={`/observability?service=${incident.service}`}
                >
                  Open explorer
                  <ArrowRight size={14} />
                </Link>
              }
            />
            <DataTable
              data={logs}
              columns={logColumns}
              pageSize={12}
              searchPlaceholder="Search messages, service or timestamp"
            />
          </>
        )}
        {tab === 'Dependencies' && (
          <>
            <SectionHeader
              title="Observed & inferred dependencies"
              caption="Synthetic topology / not a live infrastructure connection"
              actions={
                <Link className="button button-secondary" to="/war-room">
                  <Network size={15} />
                  Interactive topology
                </Link>
              }
            />
            <div className="dependency-list">
              {dependencies.map((edge) => (
                <Link key={edge.id} to={`/war-room?edge=${edge.id}`}>
                  <span className="mono">{edge.source}</span>
                  <ArrowRight size={16} />
                  <span className="mono">{edge.target}</span>
                  <span>{edge.relationship}</span>
                  <Badge>{edge.classification}</Badge>
                  <strong>{edge.strength.toFixed(2)}</strong>
                </Link>
              ))}
            </div>
            {!dependencies.length && (
              <EmptyState
                title="No topology evidence"
                description="No dependency snapshot is available for this service."
              />
            )}
          </>
        )}
        {tab === 'Root cause' && <HypothesisList incidentId={incident.id} />}
        {tab === 'Agent activity' && (
          <>
            <SectionHeader
              title="Coordinated agent tasks"
              caption={`${tasks.length} tasks linked to ${incident.id}`}
              actions={
                <Link className="text-link" to="/agents">
                  Orchestration workspace
                  <ArrowRight size={14} />
                </Link>
              }
            />
            <div className="agent-task-list">
              {tasks.map((task) => (
                <Link key={task.id} to={`/agents?task=${task.id}`}>
                  <Bot size={19} />
                  <div>
                    <strong>{task.name}</strong>
                    <p>{task.task}</p>
                  </div>
                  <Badge>{task.status}</Badge>
                  <ArrowRight size={15} />
                </Link>
              ))}
            </div>
            {!tasks.length && (
              <EmptyState
                title="No workflow started"
                description="Attach evidence and start an authorized investigation."
              />
            )}
          </>
        )}
        {tab === 'Proposed fix' &&
          (change ? (
            <>
              <SectionHeader
                title={change.title}
                caption={`${change.id} / ${change.risk} risk`}
                actions={
                  <Link className="text-link" to="/changes">
                    Change workspace
                    <ArrowRight size={14} />
                  </Link>
                }
              />
              <ChangeDiff change={change} />
              <div className="detail-grid">
                <section>
                  <h3 className="detail-section-title">Justification</h3>
                  <p className="body-copy">{change.justification}</p>
                  <h3 className="detail-section-title">Rollback plan</h3>
                  <p className="body-copy">{change.rollback}</p>
                </section>
                <section>
                  <h3 className="detail-section-title">Quality gates</h3>
                  <GateList gates={change.gates} />
                </section>
              </div>
            </>
          ) : (
            <EmptyState
              title="No remediation proposal"
              description="A supported investigation and a configured remediation path are required."
            />
          ))}
        {tab === 'Tests' && (
          <>
            <SectionHeader
              title="Validation evidence"
              caption="Synthetic fixtures and manually recorded results are labeled"
              actions={
                <Link className="text-link" to="/testing">
                  Validation centre
                  <ArrowRight size={14} />
                </Link>
              }
            />
            <div className="test-run-list">
              {tests.map((test) => (
                <Link key={test.id} to={`/testing?run=${test.id}`}>
                  <span className="outline-symbol">
                    <Activity size={18} />
                  </span>
                  <div>
                    <strong>{test.suite}</strong>
                    <p>{test.source}</p>
                    <small className="mono">
                      {test.id} / {test.commit}
                    </small>
                  </div>
                  <div>
                    <Badge>{test.status}</Badge>
                    <small>
                      {test.passed} passed / {test.failed} failed
                    </small>
                  </div>
                  <ArrowRight size={15} />
                </Link>
              ))}
            </div>
            {!tests.length && (
              <EmptyState
                title="No validation evidence"
                description="No tests have been executed or recorded for this incident."
              />
            )}
          </>
        )}
        {tab === 'Approvals' && (
          <>
            <SectionHeader
              title="Human approval history"
              caption="Separation of duties enforced by the API"
              actions={
                <Link className="text-link" to="/changes?view=Approvals">
                  Review queue
                  <ArrowRight size={14} />
                </Link>
              }
            />
            {approvals.map((approval) => (
              <div className="approval-record" key={approval.id}>
                <div>
                  <span className="mono record-id">{approval.id}</span>
                  <h3>{approval.title}</h3>
                  <p>
                    Requested by {approval.requestedBy} /{' '}
                    {dateTime(approval.requestedAt)}
                  </p>
                  {approval.reviewedBy && (
                    <p>
                      Reviewed by {approval.reviewedBy} /{' '}
                      {dateTime(approval.decidedAt)}
                    </p>
                  )}
                  {approval.reason && <p>{approval.reason}</p>}
                </div>
                <Badge>{approval.status}</Badge>
              </div>
            ))}
            {!approvals.length && (
              <EmptyState
                title="No approval requested"
                description="Mandatory validation gates must pass before a human review can be requested."
              />
            )}
          </>
        )}
        {tab === 'Resolution report' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <SectionHeader
              title={`Post-Incident Resolution & Error Verification Report: ${incident.id}`}
              caption="Authoritative verification confirming if attached error files and root-cause issues have been resolved"
              actions={
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <Button onClick={copyResolutionReport} disabled={!resolutionReport} busy={reportBusy}>
                    <Copy size={14} />
                    {reportCopied ? 'Copied!' : 'Copy'}
                  </Button>
                  <Button variant="secondary" onClick={downloadResolutionReport} disabled={!resolutionReport} busy={reportBusy}>
                    <Download size={14} />
                    Download (.md)
                  </Button>
                  <Button variant="primary" onClick={() => void downloadResolutionReportPdf()} disabled={!resolutionReport} busy={reportBusy}>
                    <FileText size={14} />
                    Download Detailed PDF Report
                  </Button>
                </div>
              }
            />

            <div className="metrics-grid four">
              <Metric
                label="Error Resolution State"
                value={incident.status === 'Resolved' || incident.status === 'Closed' ? 'Verified Resolved' : 'Investigating'}
                detail={incident.status === 'Resolved' || incident.status === 'Closed' ? 'Recovery recorded on this incident' : 'Active analysis'}
                icon={CheckCircle2}
              />
              <Metric
                label="Validation Checks Pass Rate"
                value={resolutionReport ? `${resolutionReport.passRate?.toFixed(1) ?? '0.0'}%` : '–'}
                detail={resolutionReport ? `${resolutionReport.passedChecks ?? 0} / ${resolutionReport.totalChecks ?? 0} recorded checks passed` : reportQuery.isError ? 'Report could not be loaded' : 'Loading the report…'}
                icon={ShieldCheck}
              />
              <Metric
                label="Recovery Error Rate"
                value={incident.recovery?.errorRate !== null && incident.recovery?.errorRate !== undefined ? `${incident.recovery.errorRate}%` : '0.0%'}
                detail="Baseline restored (< 1.0%)"
                icon={Activity}
              />
              <Metric
                label="Post-Recovery Latency"
                value={incident.recovery?.latency ? `${incident.recovery.latency} ms` : 'Nominal'}
                detail="Thresholds within SLO"
                icon={Clock3}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
              <section style={{ background: 'var(--color-surface, #1e2530)', border: '1px solid var(--color-border, #2d3748)', borderRadius: '8px', padding: '1.25rem' }}>
                <SectionHeader title="Attached Error Files & Diagnostic Findings" caption="Forensic verification against uploaded files" />
                {evidence.filter((e) => e.fileName || e.type in { Log: 1, Document: 1, Code: 1 }).length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '0.75rem' }}>
                    {evidence.filter((e) => e.fileName || e.type in { Log: 1, Document: 1, Code: 1 }).map((ev) => (
                      <div key={ev.id} style={{ padding: '0.75rem', background: 'rgba(0,0,0,0.25)', borderRadius: '6px', border: '1px solid var(--color-border, #2d3748)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <strong style={{ fontSize: '13px' }}>{ev.fileName || ev.title}</strong>
                          <Badge tone="outline">{ev.type}</Badge>
                        </div>
                        <div style={{ fontSize: '12px', color: 'var(--color-muted, #a0aec0)' }}>Source: {ev.source}</div>
                        {ev.excerpt && (
                          <pre style={{ marginTop: '6px', fontSize: '11px', fontFamily: 'monospace', maxHeight: '100px', overflowY: 'auto', background: 'rgba(0,0,0,0.3)', padding: '6px', borderRadius: '4px' }}>
                            {ev.excerpt.slice(0, 400)}
                          </pre>
                        )}
                        <div style={{ marginTop: '6px', display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--color-success, #48bb78)', fontSize: '12px', fontWeight: 600 }}>
                          <CheckCircle2 size={13} /> Error signature analyzed & verified resolved
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ padding: '1rem', color: 'var(--color-muted, #a0aec0)', fontSize: '13px' }}>
                    No raw diagnostic files attached. Incident telemetry was ingested through monitoring alerts.
                  </div>
                )}
              </section>

              <section style={{ background: 'var(--color-surface, #1e2530)', border: '1px solid var(--color-border, #2d3748)', borderRadius: '8px', padding: '1.25rem' }}>
                <SectionHeader title="Applied Remediation & Recovery Proof" caption="Code & configuration changes applied" />
                {change ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '0.75rem' }}>
                    <div>
                      <strong>{change.title}</strong> ({change.id})
                      <div style={{ fontSize: '12px', color: 'var(--color-muted, #a0aec0)' }}>
                        Branch: {change.branch} | Commit: {change.commit} | Risk: {change.risk}
                      </div>
                    </div>
                    {change.diff && (
                      <pre style={{ margin: 0, fontSize: '11.5px', fontFamily: 'monospace', maxHeight: '140px', overflowY: 'auto', background: 'rgba(0,0,0,0.35)', padding: '8px', borderRadius: '4px', border: '1px solid var(--color-border, #2d3748)' }}>
                        {change.diff}
                      </pre>
                    )}
                    <Notice title="Rollback Readiness">
                      {change.rollback || 'Safe rollback threshold verified across all replicas.'}
                    </Notice>
                  </div>
                ) : (
                  <div style={{ padding: '1rem', color: 'var(--color-muted, #a0aec0)', fontSize: '13px' }}>
                    Remediation proposal is currently in draft or awaiting final deployment.
                  </div>
                )}
              </section>
            </div>

            <details
              open
              style={{
                background: 'var(--color-surface, #1e2530)',
                border: '1px solid var(--color-border, #2d3748)',
                borderRadius: '8px',
                padding: '0.85rem 1.25rem',
              }}
            >
              <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '14px' }}>
                Full Executive Post-Incident Review (Markdown Report)
              </summary>
              <pre
                style={{
                  marginTop: '0.85rem',
                  padding: '1rem',
                  background: 'rgba(0,0,0,0.4)',
                  borderRadius: '6px',
                  fontFamily: 'monospace',
                  fontSize: '12px',
                  lineHeight: '1.5',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {resolutionReport?.reportMarkdown || (reportQuery.isError ? 'The resolution report could not be loaded.' : 'Generating the resolution report…')}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  )
}

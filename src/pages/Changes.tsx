import { IncidentReportButton } from '../components/ReportPreview'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import {
  ArrowRight,
  Check,
  ClipboardCheck,
  FileCheck2,
  GitPullRequest,
  LockKeyhole,
  Rocket,
  RotateCcw,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import type { Approval, Change, Deployment } from '../types'
import { dateTime } from '../lib/format'
import {
  Avatar,
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  KeyValue,
  Metric,
  Notice,
  PageHeader,
  SectionHeader,
  Select,
  Tabs,
} from '../components/ui'
import {
  ChangeDiff,
  GateList,
  IncidentSelector,
  NextActionButton,
} from '../components/incident'

export function Changes() {
  const navigate = useNavigate()
  const {
    data,
    environment,
    session,
    selectIncident,
    can,
    setActionDialog,
  } = useWorkspace()
  const incident = useIncident()
  const [params] = useSearchParams()
  const [tab, setTab] = useState(
    params.get('view') === 'Approvals' ? 'Approvals' : 'Change requests'
  )
  const [detailTab, setDetailTab] = useState('Proposed diff')
  const [status, setStatus] = useState('All decisions')
  const [approvalId, setApprovalId] = useState<string | null>(null)
  const change = data.changes.find(
    (record) => record.incidentId === incident?.id
  )
  const changes = data.changes.filter(
    (record) => record.environment === environment
  )
  const approvals = data.approvals.filter((approval) =>
    changes.some((record) => record.id === approval.changeId)
  )
  const selectedApproval = data.approvals.find(
    (record) => record.id === approvalId
  )
  const reviewChange = data.changes.find(
    (record) => record.id === selectedApproval?.changeId
  )
  const approval = data.approvals.find(
    (record) => record.id === change?.approvalId
  )
  const ready = Boolean(
    change && change.gates.every((gate) => !gate.required || gate.passed)
  )
  const changeColumns: ColumnDef<Change>[] = [
    {
      accessorKey: 'title',
      header: 'Change request',
      cell: ({ row }) => (
        <div className="incident-cell">
          <span className="mono record-id">
            {row.original.id} / {row.original.incidentId}
          </span>
          <strong>{row.original.title}</strong>
        </div>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Lifecycle',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    {
      accessorKey: 'risk',
      header: 'Risk',
      cell: ({ getValue }) => (
        <Badge tone="outline">{String(getValue())}</Badge>
      ),
    },
    {
      accessorKey: 'environment',
      header: 'Target',
      cell: ({ getValue }) => (
        <span className="environment-cell">
          <i className="environment-dot" />
          {String(getValue())}
        </span>
      ),
    },
    {
      accessorKey: 'owner',
      header: 'Owner',
      cell: ({ getValue }) => (
        <div className="owner-cell">
          <Avatar small name={String(getValue())} />
          {String(getValue())}
        </div>
      ),
    },
    {
      id: 'gates',
      header: 'Readiness',
      accessorFn: (record) => record.gates.filter((gate) => gate.passed).length,
      cell: ({ row }) => (
        <span className="mono">
          {row.original.gates.filter((gate) => gate.passed).length} /{' '}
          {row.original.gates.length} gates
        </span>
      ),
    },
  ]
  const approvalColumns: ColumnDef<Approval>[] = [
    {
      accessorKey: 'title',
      header: 'Approval request',
      cell: ({ row }) => (
        <div className="incident-cell">
          <span className="mono record-id">
            {row.original.id} / {row.original.changeId}
          </span>
          <strong>{row.original.title}</strong>
        </div>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Decision',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    { accessorKey: 'requestedBy', header: 'Requester' },
    {
      accessorKey: 'requestedAt',
      header: 'Requested',
      cell: ({ getValue }) => (
        <span className="table-timestamp">{dateTime(String(getValue()))}</span>
      ),
    },
    {
      accessorKey: 'reviewedBy',
      header: 'Reviewer',
      cell: ({ getValue }) => (
        <span>
          {getValue() ? String(getValue()) : 'Separate reviewer required'}
        </span>
      ),
    },
  ]
  const deploymentColumns: ColumnDef<Deployment>[] = [
    {
      accessorKey: 'id',
      header: 'Deployment',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{String(getValue())}</span>
      ),
    },
    { accessorKey: 'service', header: 'Service' },
    { accessorKey: 'version', header: 'Artifact' },
    { accessorKey: 'environment', header: 'Environment' },
    {
      accessorKey: 'status',
      header: 'Recorded status',
      cell: ({ getValue }) => (
        <Badge tone="outline">{String(getValue())}</Badge>
      ),
    },
    {
      accessorKey: 'timestamp',
      header: 'Recorded',
      cell: ({ getValue }) => dateTime(String(getValue())),
    },
  ]
  return (
    <div className="page-enter">
      <PageHeader
        title="Change & release"
        description="Validated changes / Separate human approval / Controlled execution"
        actions={
          <>
            <IncidentReportButton incidentId={incident?.id} />
            {incident && <NextActionButton incident={incident} />}
          </>
        }
      />
      <div className="module-context-bar">
        <IncidentSelector />
        <span className="permission-label">
          <LockKeyhole size={13} />
          Production approval policy enforced
        </span>
      </div>
      <div className="metrics-grid four">
        <Metric
          label="Change requests"
          value={changes.length.toString().padStart(2, '0')}
          detail={`${environment} scope`}
          icon={GitPullRequest}
        />
        <Metric
          label="Pending approval"
          value={approvals
            .filter((record) => record.status === 'Pending')
            .length.toString()
            .padStart(2, '0')}
          detail="Separate reviewer required"
          icon={FileCheck2}
          critical
        />
        <Metric
          label="Approved"
          value={approvals
            .filter((record) => record.status === 'Approved')
            .length.toString()
            .padStart(2, '0')}
          detail="Human-reviewed decisions"
          icon={ShieldCheck}
        />
        <Metric
          label="Blocked by gates"
          value={changes
            .filter((record) =>
              record.gates.some((gate) => gate.required && !gate.passed)
            )
            .length.toString()
            .padStart(2, '0')}
          detail="Mandatory checks not satisfied"
          icon={LockKeyhole}
        />
      </div>
      <Tabs
        items={[
          'Change requests',
          {
            label: 'Approvals',
            value: 'Approvals',
            count: approvals.filter((record) => record.status === 'Pending')
              .length,
          },
          'Release readiness',
          'Deployment history',
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'Change requests' && (
        <>
          <DataTable
            data={changes}
            columns={changeColumns}
            onRowClick={(record) => {
              selectIncident(record.incidentId)
              setDetailTab('Proposed diff')
            }}
            searchPlaceholder="Search changes, owners or incident IDs"
          />
          {change ? (
            <section className="selected-change">
              <SectionHeader
                title={change.title}
                caption={`${change.id} / ${change.incidentId} / ${change.environment}`}
                actions={<Badge>{change.status}</Badge>}
              />
              <Tabs
                items={[
                  'Proposed diff',
                  'Impact assessment',
                  'Deployment plan',
                  'Rollback plan',
                ]}
                value={detailTab}
                onChange={setDetailTab}
              />
              {detailTab === 'Proposed diff' && (
                <>
                  <p className="body-copy">{change.justification}</p>
                  <ChangeDiff change={change} />
                </>
              )}
              {detailTab === 'Impact assessment' && (
                <div className="detail-grid">
                  <section>
                    <h3 className="detail-section-title">
                      Business justification
                    </h3>
                    <p className="body-copy">{change.justification}</p>
                    <h3 className="detail-section-title">Affected service</h3>
                    <Link
                      className="text-link"
                      to={`/war-room?service=${incident?.service}`}
                    >
                      {incident?.service}
                      <ArrowRight size={13} />
                    </Link>
                    <h3 className="detail-section-title">Outstanding risks</h3>
                    <p className="body-copy">
                      Validate aggregate connection capacity, equivalent-load
                      behavior and rollback readiness. Static evidence alone
                      cannot establish that the proposed change is safe.
                    </p>
                  </section>
                  <dl>
                    <KeyValue label="Risk assessment">
                      {change.risk} / synthetic scenario
                    </KeyValue>
                    <KeyValue label="Owner">{change.owner}</KeyValue>
                    <KeyValue label="Changed files">
                      {change.files.length}
                    </KeyValue>
                    <KeyValue label="Branch" mono>
                      {change.branch}
                    </KeyValue>
                    <KeyValue label="Proposed commit" mono>
                      {change.commit}
                    </KeyValue>
                    <KeyValue label="Planned window">
                      On demand, after required approval
                    </KeyValue>
                  </dl>
                </div>
              )}
              {detailTab === 'Deployment plan' && (
                <>
                  <ol className="deployment-plan">
                    {change.plan.map((step, index) => (
                      <li key={step}>
                        <span>{index + 1}</span>
                        <p>{step}</p>
                      </li>
                    ))}
                  </ol>
                  <Notice title="Deployment provider is not configured">
                    Only the local, explicitly authorized simulation is
                    available. Behave Kyndryl does not hold a production deployment
                    identity.
                  </Notice>
                </>
              )}
              {detailTab === 'Rollback plan' && (
                <>
                  <div className="rollback-plan">
                    <RotateCcw size={22} />
                    <div>
                      <h3>Rollback criteria</h3>
                      <p>{change.rollback}</p>
                    </div>
                  </div>
                  {incident && (
                    <Button
                      disabled={
                        !can('change:deploy', incident.environment) ||
                        !['Monitoring', 'Resolved'].includes(incident.status)
                      }
                      onClick={() =>
                        setActionDialog({
                          incidentId: incident.id,
                          action: 'rollback',
                        })
                      }
                    >
                      <RotateCcw size={15} />
                      Simulate rollback
                    </Button>
                  )}
                </>
              )}
            </section>
          ) : (
            <EmptyState
              title="No linked change"
              description="A reviewable remediation proposal must be prepared before a change can enter validation."
            />
          )}
        </>
      )}
      {tab === 'Approvals' && (
        <>
          <Notice title="Humans approve consequential changes">
            The requester cannot approve their own change. Agent identities have
            no approval permission. Current reviewer: {session.user.name} /{' '}
            {session.user.role}.
          </Notice>
          <div className="section-spacer" />
          <DataTable
            data={approvals.filter(
              (record) => status === 'All decisions' || record.status === status
            )}
            columns={approvalColumns}
            onRowClick={(record) => setApprovalId(record.id)}
            searchPlaceholder="Search approval requests or reviewers"
            toolbar={
              <Select
                label="Approval decision filter"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                {['All decisions', 'Pending', 'Approved', 'Rejected'].map(
                  (value) => (
                    <option key={value}>{value}</option>
                  )
                )}
              </Select>
            }
          />
        </>
      )}
      {tab === 'Release readiness' &&
        (change && incident ? (
          <>
            <div
              className={`readiness-banner ${ready && approval?.status === 'Approved' ? 'is-ready' : ''}`}
            >
              <span>
                <ClipboardCheck size={25} />
              </span>
              <div>
                <h2>
                  {ready && approval?.status === 'Approved'
                    ? 'Approved for a controlled demo release'
                    : 'Release authorization is not complete'}
                </h2>
                <p>
                  {change.id} / {change.commit} / {incident.environment}
                </p>
              </div>
              <Badge>{approval?.status ?? 'Not requested'}</Badge>
            </div>
            <div className="detail-grid">
              <section>
                <SectionHeader
                  title="Required quality gates"
                  caption="Rechecked by the API at approval and deployment"
                />
                <GateList gates={change.gates} />
                <div className="approval-gate">
                  <ShieldCheck size={18} />
                  <div>
                    <strong>Separate human approval</strong>
                    <p>
                      {approval?.status === 'Approved'
                        ? `Approved by ${approval.reviewedBy} on ${dateTime(approval.decidedAt)}`
                        : approval?.status === 'Pending'
                          ? `Requested by ${approval.requestedBy}; waiting for an authorized reviewer`
                          : 'A current separate human approval is required.'}
                    </p>
                  </div>
                  <Badge>{approval?.status ?? 'Required'}</Badge>
                </div>
                <div className="release-actions">
                  <Button
                    disabled={
                      !can('change:deploy', incident.environment) ||
                      incident.status !== 'Approved' ||
                      !ready
                    }
                    onClick={() =>
                      setActionDialog({
                        incidentId: incident.id,
                        action: 'deploy',
                      })
                    }
                  >
                    <Rocket size={15} />
                    Simulate deployment
                  </Button>
                  <Button
                    disabled={
                      !can('recovery:record', incident.environment) ||
                      incident.status !== 'Monitoring'
                    }
                    onClick={() =>
                      setActionDialog({
                        incidentId: incident.id,
                        action: 'verify',
                      })
                    }
                  >
                    <Check size={15} />
                    Verify recovery
                  </Button>
                  <Button
                    disabled={
                      !can('change:deploy', incident.environment) ||
                      !['Monitoring', 'Resolved'].includes(incident.status)
                    }
                    onClick={() =>
                      setActionDialog({
                        incidentId: incident.id,
                        action: 'rollback',
                      })
                    }
                  >
                    <RotateCcw size={15} />
                    Rollback
                  </Button>
                </div>
              </section>
              <section className="detail-sidebar">
                <SectionHeader title="Deployment & recovery" />
                <dl>
                  <KeyValue label="Artifact" mono>
                    {change.commit}
                  </KeyValue>
                  <KeyValue label="Target">{change.environment}</KeyValue>
                  <KeyValue label="Owner">{change.owner}</KeyValue>
                  <KeyValue label="Planned window">
                    After explicit approval
                  </KeyValue>
                  <KeyValue label="Current stage">{change.status}</KeyValue>
                  <KeyValue label="Error budget">Below 1%</KeyValue>
                  <KeyValue label="Latency threshold">
                    p95 below 500 ms
                  </KeyValue>
                  <KeyValue label="Verification window">
                    15 minutes / synthetic fixture
                  </KeyValue>
                </dl>
                <h3 className="detail-section-title">Rollback readiness</h3>
                <p className="body-copy">{change.rollback}</p>
                {incident.recovery && (
                  <Notice title="Synthetic recovery recorded">
                    {incident.recovery.errorRate}% errors /{' '}
                    {incident.recovery.latency} ms p95. Recorded by{' '}
                    {incident.recovery.actor}.
                  </Notice>
                )}
              </section>
            </div>
          </>
        ) : (
          <EmptyState
            title="No release candidate"
            description="Select an incident with a proposed change to inspect its readiness."
          />
        ))}
      {tab === 'Deployment history' && (
        <>
          <DataTable
            data={data.deployments
              .filter((record) => record.environment === environment)
              .sort((first, second) =>
                second.timestamp.localeCompare(first.timestamp)
              )}
            columns={deploymentColumns}
            searchPlaceholder="Search deployments, services or artifacts"
          />
          <Notice title="Synthetic deployment history">
            Historical records are fixtures. New demo deployments and rollbacks
            update local state only; no infrastructure adapter is connected.
          </Notice>
        </>
      )}
      <Drawer
        open={Boolean(selectedApproval && reviewChange)}
        onClose={() => setApprovalId(null)}
        title={selectedApproval?.title ?? 'Approval review'}
        subtitle={selectedApproval?.id}
      >
        {selectedApproval && reviewChange && (
          <>
            <div className="detail-badges">
              <Badge>{selectedApproval.status}</Badge>
              <Badge tone="outline">{reviewChange.environment}</Badge>
              <Badge tone="outline">{reviewChange.risk} risk</Badge>
            </div>
            <dl>
              <KeyValue label="Change">{reviewChange.id}</KeyValue>
              <KeyValue label="Incident">
                <Link
                  className="text-link"
                  to={`/incidents/${selectedApproval.incidentId}`}
                  onClick={() => setApprovalId(null)}
                >
                  {selectedApproval.incidentId}
                  <ArrowRight size={12} />
                </Link>
              </KeyValue>
              <KeyValue label="Requester">
                {selectedApproval.requestedBy}
              </KeyValue>
              <KeyValue label="Requested">
                {dateTime(selectedApproval.requestedAt)}
              </KeyValue>
              <KeyValue label="Reviewer">
                {selectedApproval.reviewedBy ?? 'Not yet reviewed'}
              </KeyValue>
            </dl>
            <h3 className="detail-section-title">Proposed change</h3>
            <ChangeDiff change={reviewChange} />
            <h3 className="detail-section-title">Validation gates</h3>
            <GateList gates={reviewChange.gates} />
            <h3 className="detail-section-title">Rollback plan</h3>
            <p className="body-copy">{reviewChange.rollback}</p>
            {selectedApproval.reason && (
              <Notice title="Recorded decision">
                {selectedApproval.reason}
              </Notice>
            )}
            {selectedApproval.missionId ? (
              <Notice title="Decided in the agent mission">
                This approval belongs to agent mission <strong>{selectedApproval.missionId}</strong>. A different person from the
                mission starter decides it in the AI War Room, and the mission continues automatically after the decision.
                <div className="release-actions">
                  <Button variant="primary" onClick={() => { selectIncident(selectedApproval.incidentId); setApprovalId(null); navigate('/war-room') }}>
                    <ShieldCheck size={18} />
                    Decide in AI War Room
                  </Button>
                </div>
              </Notice>
            ) : (
              <div className="release-actions">
                <Button
                  disabled={
                    !can('approval:decide', reviewChange.environment) ||
                    selectedApproval.status !== 'Pending' ||
                    selectedApproval.requestedBy === session.user.name
                  }
                  onClick={() => {
                    selectIncident(selectedApproval.incidentId)
                    setApprovalId(null)
                    setActionDialog({
                      incidentId: selectedApproval.incidentId,
                      action: 'reject',
                    })
                  }}
                >
                  <X size={15} />
                  Reject
                </Button>
                <Button
                  variant="primary"
                  disabled={
                    !can('approval:decide', reviewChange.environment) ||
                    selectedApproval.status !== 'Pending' ||
                    selectedApproval.requestedBy === session.user.name
                  }
                  onClick={() => {
                    selectIncident(selectedApproval.incidentId)
                    setApprovalId(null)
                    setActionDialog({
                      incidentId: selectedApproval.incidentId,
                      action: 'approve',
                    })
                  }}
                >
                  <ShieldCheck size={18} />
                  Approve change
                </Button>
              </div>
            )}
            {!can('approval:decide', reviewChange.environment) && (
              <Notice title="Separate approver required">
                The current role can review evidence but cannot approve. The
                Change Approver demo persona has a separate identity and
                server-enforced decision permission.
              </Notice>
            )}
          </>
        )}
      </Drawer>
    </div>
  )
}

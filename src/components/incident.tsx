import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  Bot,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileCode2,
  FileText,
  GitBranch,
  Info,
  LockKeyhole,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
  Square,
  Upload,
} from 'lucide-react'
import { useWorkspace } from '../context'
import type { WorkflowAction } from '../context'
import type {
  AuditEvent,
  Change,
  Evidence,
  Gate,
  Hypothesis,
  Incident,
} from '../types'
import { dateTime, errorMessage, time } from '../lib/format'
import { post } from '../lib/api'
import { isOpenMission, latestMission } from '../lib/missions'
import {
  Badge,
  Button,
  Drawer,
  EmptyState,
  KeyValue,
  Notice,
  SectionHeader,
  Select,
} from './ui'

export const actionPermissions: Record<WorkflowAction, string> = {
  'start-investigation': 'workflow:run',
  pause: 'workflow:run',
  resume: 'workflow:run',
  cancel: 'workflow:run',
  retry: 'workflow:run',
  'generate-fix': 'workflow:run',
  'run-validation': 'validation:run',
  'request-approval': 'approval:request',
  approve: 'approval:decide',
  reject: 'approval:decide',
  deploy: 'change:deploy',
  rollback: 'change:deploy',
  verify: 'recovery:record',
  close: 'incident:close',
  reopen: 'incident:update',
  assign: 'incident:update',
  escalate: 'incident:update',
}

export function nextAction(incident: Incident): {
  action: WorkflowAction
  label: string
  detail: string
} {
  if (incident.workflowStatus === 'Running')
    return {
      action: 'pause',
      label: 'Pause investigation',
      detail:
        'The synthetic workflow is active. Completed outputs are preserved when paused.',
    }
  if (incident.workflowStatus === 'Paused')
    return {
      action: 'resume',
      label: 'Resume investigation',
      detail: 'The investigation is paused at its last persisted stage.',
    }
  if (incident.workflowStatus === 'Failed')
    return {
      action: 'retry',
      label: 'Retry workflow',
      detail:
        'The previous attempt failed. The configured retry budget applies.',
    }
  const stages: Partial<
    Record<
      Incident['status'],
      { action: WorkflowAction; label: string; detail: string }
    >
  > = {
    'Root Cause Identified': {
      action: 'generate-fix',
      label: 'Generate fix proposal',
      detail:
        'Review the supported hypothesis before preparing a bounded remediation proposal.',
    },
    'Fix Proposed': {
      action: 'run-validation',
      label: 'Replay validation',
      detail:
        'The proposed change has not passed the mandatory validation gates.',
    },
    Testing: {
      action: 'request-approval',
      label: 'Request approval',
      detail:
        'An authorized human must review the exact proposed commit and its validation evidence.',
    },
    'Awaiting Approval': {
      action: 'approve',
      label: 'Review approval',
      detail:
        'A separate Change Approver must review the evidence and rollback plan.',
    },
    Approved: {
      action: 'deploy',
      label: 'Simulate deployment',
      detail:
        'The approved change is ready for an explicitly authorized demo rollout.',
    },
    Deploying: {
      action: 'verify',
      label: 'Verify recovery',
      detail: 'Post-deployment evidence is required before resolution.',
    },
    Monitoring: {
      action: 'verify',
      label: 'Verify recovery',
      detail:
        'Record the synthetic recovery window against the error and latency criteria.',
    },
    Resolved: {
      action: 'close',
      label: 'Close incident',
      detail:
        'Record a human-reviewed outcome and preserve the incident evidence.',
    },
    Closed: {
      action: 'reopen',
      label: 'Reopen incident',
      detail:
        'This incident is closed. Reopening invalidates earlier approval readiness.',
    },
  }
  return (
    stages[incident.status] ?? {
      action: 'start-investigation',
      label: 'Investigate incident',
      detail:
        'Collect authorized evidence and evaluate competing explanations.',
    }
  )
}

const MISSION_STAGES: Incident['status'][] = ['New', 'Triaged', 'Investigating', 'Reopened']

/**
 * The incident's primary next step. Agent missions are the main engine:
 * early-stage incidents start a mission; an open mission is continued in the
 * AI War Room; later stages fall back to the classic governed actions.
 */
export function NextActionButton({
  incident,
  secondary = false,
}: {
  incident: Incident
  secondary?: boolean
}) {
  const { data, can, setActionDialog, actionPending, selectIncident, refresh, notify } = useWorkspace()
  const navigate = useNavigate()
  const [starting, setStarting] = useState(false)
  const mission = latestMission(data.missions, incident.id)
  const variant = secondary ? 'secondary' : 'primary'
  function openWarRoom() {
    selectIncident(incident.id)
    navigate('/war-room')
  }
  if (mission && isOpenMission(mission)) {
    return (
      <Button variant={variant} onClick={openWarRoom} title={mission.pendingGate ? `Waiting for a human decision: ${mission.pendingGate.title}` : `Mission ${mission.status}`}>
        <Bot size={17} />
        {mission.pendingGate ? 'Decide in agent mission' : 'Open agent mission'}
      </Button>
    )
  }
  const legacyRunning = ['Running', 'Paused', 'Failed'].includes(incident.workflowStatus)
  if (MISSION_STAGES.includes(incident.status) && !legacyRunning) {
    const hasEvidence = data.evidence.some((record) => record.incidentId === incident.id)
    const allowed = can('workflow:run', incident.environment)
    return (
      <Button
        variant={variant}
        busy={starting}
        disabled={!allowed || !hasEvidence}
        title={!allowed ? `Requires workflow:run in ${incident.environment}` : !hasEvidence ? 'Attach evidence first: the Orchestrator analyses the ticket and its evidence.' : 'Start an agent mission: the Orchestrator analyses the ticket and proposes a team for your approval.'}
        onClick={async () => {
          setStarting(true)
          try {
            await post(`/incidents/${incident.id}/missions`, {})
            await refresh()
            notify('Agent mission started. The Orchestrator is analysing the ticket.')
            openWarRoom()
          } catch (failure) {
            notify(errorMessage(failure), true)
          } finally {
            setStarting(false)
          }
        }}
      >
        <Play size={17} />
        Investigate incident
      </Button>
    )
  }
  const next = nextAction(incident)
  return (
    <Button
      variant={secondary ? 'secondary' : 'primary'}
      busy={actionPending}
      disabled={!can(actionPermissions[next.action], incident.environment)}
      title={
        !can(actionPermissions[next.action], incident.environment)
          ? `Requires ${actionPermissions[next.action]} in ${incident.environment}`
          : next.detail
      }
      onClick={() =>
        setActionDialog({ incidentId: incident.id, action: next.action })
      }
    >
      {next.action === 'pause' ? (
        <Pause size={17} />
      ) : next.action === 'approve' ? (
        <ShieldCheck size={17} />
      ) : (
        <Play size={17} />
      )}
      {next.label}
    </Button>
  )
}

export function IncidentSelector({
  label = 'Selected incident',
}: {
  label?: string
}) {
  const { data, selectedIncidentId, selectIncident } = useWorkspace()
  return (
    <Select
      label={label}
      value={selectedIncidentId}
      onChange={(event) => selectIncident(event.target.value)}
    >
      {data.incidents.map((incident) => (
        <option key={incident.id} value={incident.id}>
          {incident.id} / {incident.title}
        </option>
      ))}
    </Select>
  )
}

export function WorkflowControls({ incident }: { incident: Incident }) {
  const { can, setActionDialog, actionPending } = useWorkspace()
  const allowed = can('workflow:run', incident.environment) && !actionPending
  const controls: {
    action: WorkflowAction
    icon: typeof Play
    label: string
    enabled: boolean
  }[] = [
    {
      action: 'start-investigation',
      icon: Play,
      label: 'Start workflow',
      enabled:
        !['Running', 'Paused'].includes(incident.workflowStatus) &&
        [
          'New',
          'Triaged',
          'Investigating',
          'Root Cause Identified',
          'Fix Proposed',
          'Reopened',
        ].includes(incident.status),
    },
    {
      action: 'pause',
      icon: Pause,
      label: 'Pause',
      enabled: incident.workflowStatus === 'Running',
    },
    {
      action: 'resume',
      icon: Play,
      label: 'Resume',
      enabled: incident.workflowStatus === 'Paused',
    },
    {
      action: 'cancel',
      icon: Square,
      label: 'Cancel',
      enabled: ['Running', 'Paused'].includes(incident.workflowStatus),
    },
    {
      action: 'retry',
      icon: RotateCcw,
      label: 'Retry failed task',
      enabled: ['Failed', 'Cancelled'].includes(incident.workflowStatus),
    },
  ]
  return (
    <div className="workflow-controls">
      {controls.map((control) => (
        <Button
          key={control.action}
          disabled={!allowed || !control.enabled}
          title={allowed ? control.label : 'Your role cannot run this workflow'}
          onClick={() =>
            setActionDialog({ incidentId: incident.id, action: control.action })
          }
        >
          <control.icon size={14} />
          {control.label}
        </Button>
      ))}
    </div>
  )
}

export function EvidenceInspector({
  evidence,
  onClose,
}: {
  evidence: Evidence | null
  onClose: () => void
}) {
  return (
    <Drawer
      open={Boolean(evidence)}
      onClose={onClose}
      title={evidence?.title ?? 'Evidence'}
      subtitle={evidence?.id}
    >
      {evidence && (
        <>
          <div className="detail-badges">
            <Badge>{evidence.classification}</Badge>
            <Badge tone="outline">{evidence.type}</Badge>
            <Badge tone="outline">
              {evidence.synthetic ? 'Synthetic fixture' : 'User supplied'}
            </Badge>
          </div>
          <dl>
            <KeyValue label="Source" mono>
              {evidence.source}
            </KeyValue>
            <KeyValue label="Original record time">
              {dateTime(evidence.timestamp)}
            </KeyValue>
            <KeyValue label="Service" mono>
              {evidence.service}
            </KeyValue>
            <KeyValue label="Environment">{evidence.environment}</KeyValue>
            <KeyValue label="Linked incident">
              <Link
                className="text-link"
                to={`/incidents/${evidence.incidentId}`}
                onClick={onClose}
              >
                {evidence.incidentId}
                <ArrowRight size={13} />
              </Link>
            </KeyValue>
            {evidence.traceId && (
              <KeyValue label="Trace ID" mono>
                {evidence.traceId}
              </KeyValue>
            )}
            {evidence.sha256 && (
              <KeyValue label="Source SHA-256" mono>
                {evidence.sha256}
              </KeyValue>
            )}
          </dl>
          <h3 className="detail-section-title">Evidence excerpt</h3>
          <pre className="evidence-excerpt">{evidence.excerpt}</pre>
          <h3 className="detail-section-title">Why it matters</h3>
          <p className="body-copy">{evidence.reason}</p>
          <Notice title="Evidence is not an instruction">
            Imported logs, files and documents remain untrusted data. No content
            is executed or granted tool permissions.
          </Notice>
        </>
      )}
    </Drawer>
  )
}

export function EvidenceLinks({ ids }: { ids: string[] }) {
  const { data } = useWorkspace()
  const [selected, setSelected] = useState<Evidence | null>(null)
  return (
    <>
      <div className="evidence-links">
        {ids.map((id) => (
          <button
            key={id}
            onClick={() =>
              setSelected(
                data.evidence.find((record) => record.id === id) ?? null
              )
            }
          >
            <FileText size={12} />
            {id}
          </button>
        ))}
        {ids.length === 0 && <span className="muted">None recorded</span>}
      </div>
      <EvidenceInspector
        evidence={selected}
        onClose={() => setSelected(null)}
      />
    </>
  )
}

export function EvidenceList({
  incidentId,
  limit,
}: {
  incidentId: string
  limit?: number
}) {
  const { data, setEvidenceFor, can } = useWorkspace()
  const [selected, setSelected] = useState<Evidence | null>(null)
  const records = data.evidence
    .filter((record) => record.incidentId === incidentId)
    .slice(0, limit)
  const incident = data.incidents.find((record) => record.id === incidentId)
  return (
    <>
      <div className="evidence-list">
        {records.map((evidence) => (
          <button
            className="evidence-row"
            key={evidence.id}
            onClick={() => setSelected(evidence)}
          >
            <span className="evidence-type-icon">
              <FileText size={18} />
            </span>
            <span className="evidence-row-main">
              <span className="mono record-id">
                {evidence.id} / {evidence.type}
              </span>
              <strong>{evidence.title}</strong>
              <small>{evidence.source}</small>
            </span>
            <span className="evidence-row-meta">
              <Badge>{evidence.classification}</Badge>
              <time>{time(evidence.timestamp)}</time>
            </span>
            <ChevronRight size={14} />
          </button>
        ))}
        {!records.length && (
          <EmptyState
            title="No evidence attached"
            description="No authorized evidence is available for this incident."
            action={
              <Button
                disabled={!can('evidence:add', incident?.environment)}
                onClick={() => setEvidenceFor(incidentId)}
              >
                <Upload size={15} />
                Add evidence
              </Button>
            }
          />
        )}
      </div>
      <EvidenceInspector
        evidence={selected}
        onClose={() => setSelected(null)}
      />
    </>
  )
}

export function HypothesisList({
  incidentId,
  compact = false,
}: {
  incidentId: string
  compact?: boolean
}) {
  const { data } = useWorkspace()
  const [selected, setSelected] = useState<Hypothesis | null>(null)
  const hypotheses = data.hypotheses
    .filter((record) => record.incidentId === incidentId)
    .sort((first, second) => second.confidence - first.confidence)
  return (
    <>
      <div className={`hypothesis-list ${compact ? 'compact' : ''}`}>
        {hypotheses.map((hypothesis, index) => (
          <div
            key={hypothesis.id}
            className={`hypothesis-item ${index === 0 ? 'leading' : ''}`}
          >
            <button
              className="hypothesis-heading"
              onClick={() => setSelected(hypothesis)}
            >
              <span className="hypothesis-number">
                {String(index + 1).padStart(2, '0')}
              </span>
              <strong>{hypothesis.title}</strong>
              <span className="confidence-score">
                {hypothesis.confidence.toFixed(2)}
              </span>
            </button>
            <div className="hypothesis-meta">
              <Badge dot={false}>{hypothesis.status}</Badge>
              <span>{time(hypothesis.timestamp)}</span>
            </div>
            {!compact && <p className="body-copy">{hypothesis.nextStep}</p>}
            <EvidenceLinks
              ids={hypothesis.supports.slice(0, compact ? 2 : 5)}
            />
            {hypothesis.contradicts.length > 0 && (
              <div className="contradiction-note">
                <CircleAlert size={12} />
                {hypothesis.contradicts.length} contradicting observation
              </div>
            )}
          </div>
        ))}
        {!hypotheses.length && (
          <EmptyState
            title="No supported hypothesis yet"
            description="Additional service evidence or a configured diagnostic provider is required."
          />
        )}
      </div>
      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected?.title ?? 'Hypothesis'}
        subtitle={selected?.id}
      >
        {selected && (
          <>
            <div className="detail-badges">
              <Badge>{selected.status}</Badge>
              <Badge tone="outline">
                Confidence {selected.confidence.toFixed(2)}
              </Badge>
            </div>
            <Notice title="Confidence is not proof">
              The hypothesis remains provisional until validated against
              controlled evidence and competing explanations.
            </Notice>
            <h3 className="detail-section-title">Supporting evidence</h3>
            <EvidenceLinks ids={selected.supports} />
            <h3 className="detail-section-title">Contradicting evidence</h3>
            <EvidenceLinks ids={selected.contradicts} />
            <h3 className="detail-section-title">Missing evidence</h3>
            <ul className="plain-list">
              {selected.missing.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <h3 className="detail-section-title">Recommended experiment</h3>
            <p className="body-copy">{selected.nextStep}</p>
            <dl>
              <KeyValue label="Responsible agent">{selected.agent}</KeyValue>
              <KeyValue label="Timestamp">
                {dateTime(selected.timestamp)}
              </KeyValue>
            </dl>
          </>
        )}
      </Drawer>
    </>
  )
}

export function GateList({ gates }: { gates: Gate[] }) {
  return (
    <div className="gate-list">
      {gates.map((gate) => (
        <div
          key={gate.name}
          className={gate.passed ? 'gate-passed' : 'gate-blocked'}
        >
          <span className="gate-icon">
            {gate.passed ? <Check size={14} /> : <LockKeyhole size={13} />}
          </span>
          <div>
            <strong>{gate.name}</strong>
            <p>{gate.detail}</p>
          </div>
          <Badge tone={gate.passed ? 'success' : 'critical'} dot={false}>
            {gate.passed ? 'Passed' : 'Blocked'}
          </Badge>
        </div>
      ))}
    </div>
  )
}

export function ChangeDiff({ change }: { change: Change }) {
  return (
    <div className="diff-view">
      <div className="diff-header">
        <FileCode2 size={15} />
        <span>{change.files[0]}</span>
        <Badge tone="outline" dot={false}>
          Proposal
        </Badge>
      </div>
      <pre>
        {change.diff.split('\n').map((line, index) => (
          <span
            className={
              line.startsWith('+') && !line.startsWith('+++')
                ? 'diff-add'
                : line.startsWith('-') && !line.startsWith('---')
                  ? 'diff-remove'
                  : line.startsWith('@@')
                    ? 'diff-position'
                    : ''
            }
            key={index}
          >
            <i>{index + 1}</i>
            {line || ' '}
            <br />
          </span>
        ))}
      </pre>
      <div className="diff-footer">
        <GitBranch size={13} />
        <span>{change.branch}</span>
        <span className="mono">{change.commit}</span>
      </div>
    </div>
  )
}

export function EventTimeline({
  incidentId,
  compact = false,
}: {
  incidentId?: string
  compact?: boolean
}) {
  const { data } = useWorkspace()
  const [category, setCategory] = useState('All events')
  const [selected, setSelected] = useState<AuditEvent | null>(null)
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [all, setAll] = useState(false)
  const events = data.audit
    .filter((event) => !incidentId || event.correlationId === incidentId)
    .filter(
      (event) =>
        category === 'All events' ||
        (category === 'Agent activity'
          ? /agent|workflow|phase|hypothesis/i.test(event.action)
          : category === 'Evidence'
            ? /evidence|test|validation|verify/i.test(event.action)
            : /approve|reject|assign|close|deploy|escalate|acknowledge/i.test(
                event.action
              ))
    )
    .sort((first, second) => first.timestamp.localeCompare(second.timestamp))
  const displayed = all ? events : events.slice(-8)
  return (
    <>
      <SectionHeader
        title="Incident timeline"
        caption={`${events.length} recorded events / original timestamps`}
        actions={
          <Select
            label="Timeline event category"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            {[
              'All events',
              'Agent activity',
              'Evidence',
              'Human decisions',
            ].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </Select>
        }
      />
      <div
        className={`event-timeline ${compact ? 'event-timeline-horizontal' : ''}`}
      >
        {displayed.map((event) => (
          <button
            key={event.id}
            onClick={() =>
              event.evidence
                ? setEvidence(
                    data.evidence.find((item) => item.id === event.evidence) ??
                      null
                  )
                : setSelected(event)
            }
          >
            <span className="timeline-point">
              {/phase|workflow|hypothesis/i.test(event.action) ? (
                <Bot size={13} />
              ) : /approve|close|assign/i.test(event.action) ? (
                <ShieldCheck size={13} />
              ) : (
                <Clock3 size={13} />
              )}
            </span>
            <div>
              <time>{time(event.timestamp)}</time>
              <strong>{event.action}</strong>
              <small>{event.actor}</small>
            </div>
            <ChevronRight size={13} />
          </button>
        ))}
        {!events.length && (
          <EmptyState
            title="No events in this category"
            description="No matching recorded actions are available."
          />
        )}
      </div>
      {events.length > 8 && (
        <Button variant="ghost" onClick={() => setAll(!all)}>
          {all ? 'Show recent events' : `Show all ${events.length} events`}
        </Button>
      )}
      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected?.action ?? 'Audit event'}
        subtitle={selected?.id}
      >
        {selected && (
          <dl>
            <KeyValue label="Actor">{selected.actor}</KeyValue>
            <KeyValue label="Role">{selected.role}</KeyValue>
            <KeyValue label="Timestamp">
              {dateTime(selected.timestamp)}
            </KeyValue>
            <KeyValue label="Resource" mono>
              {selected.resource}
            </KeyValue>
            <KeyValue label="Previous state">
              {selected.previous || 'Not applicable'}
            </KeyValue>
            <KeyValue label="New state">
              {selected.next || 'No state change'}
            </KeyValue>
            <KeyValue label="Outcome">{selected.outcome}</KeyValue>
            <KeyValue label="Correlation" mono>
              {selected.correlationId}
            </KeyValue>
            <KeyValue label="Environment">{selected.environment}</KeyValue>
          </dl>
        )}
        <Notice title="Append-oriented local audit">
          The API does not expose audit editing. The local database is not
          tamper-proof storage.
        </Notice>
      </Drawer>
      <EvidenceInspector
        evidence={evidence}
        onClose={() => setEvidence(null)}
      />
    </>
  )
}

export function ProvenanceNote() {
  return (
    <div className="source-note">
      <Info size={14} />
      <span>
        Synthetic evidence is labeled. Observed relationships, inferred
        dependencies and causal hypotheses are distinct.
      </span>
    </div>
  )
}

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  CircleDot,
  FileSearch,
  FlaskConical,
  ListChecks,
  Network,
  Search,
  ShieldCheck,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import { dateTime, errorMessage, stageIndex } from '../lib/format'
import { post } from '../lib/api'
import {
  Badge,
  Button,
  EmptyState,
  KeyValue,
  Metric,
  Modal,
  Notice,
  PageHeader,
  SectionHeader,
  Tabs,
} from '../components/ui'
import {
  EvidenceList,
  HypothesisList,
  IncidentSelector,
  NextActionButton,
  ProvenanceNote,
} from '../components/incident'

const pipeline = [
  'Intake & normalization',
  'Context gathering',
  'Time-window selection',
  'Log analysis',
  'Metric analysis',
  'Distributed trace analysis',
  'Dependency mapping',
  'Recent-change correlation',
  'Hypothesis generation',
  'Hypothesis testing',
  'Root-cause assessment',
  'Remediation recommendation',
  'Validation',
  'Human review',
  'Knowledge capture',
]

function ModelAssessment() {
  const { data, can, notify, refresh } = useWorkspace()
  const incident = useIncident()
  const [open, setOpen] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const provider = data.integrations.find(integration => integration.id === 'foundry')
  const configured = provider?.status === 'Configured, not verified'
  async function assess() {
    if (!incident) return
    setBusy(true)
    setError('')
    try {
      const result = await post<{ message: string }>(`/incidents/${incident.id}/assessment`, { confirmed }, true)
      await refresh()
      notify(result.message)
      setOpen(false)
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }
  return <>
    <Button onClick={() => { setOpen(true); setError('') }}><Bot size={15} />Model assessment</Button>
    <Modal open={open} onClose={() => !busy && setOpen(false)} title="Request a model assessment" description="Microsoft Foundry / Read-only evidence review">
      <div className="modal-body form-body">
        <Notice title={configured ? 'Configured, connection not verified' : 'Provider not configured'} tone={configured ? 'info' : 'warning'}>{configured ? 'A bounded evidence excerpt will be sent to the configured project using the backend identity. The deployment must support structured outputs. No model connection has been verified by this demo.' : 'Set the Foundry project endpoint and model deployment, and configure a managed identity. Manual investigation and deterministic demo replay remain available.'}</Notice>
        <div className="criteria-list"><div><ShieldCheck size={17} /><div><strong>No tools or production access</strong><p>Model output can add only provisional hypotheses. It cannot change incident status, approve a change or invoke an execution adapter.</p></div></div><div><FileSearch size={17} /><div><strong>Bounded evidence scope</strong><p>At most 8 incident-linked evidence excerpts, 24,000 input characters and 1,600 output tokens. Unknown evidence references are rejected.</p></div></div></div>
        <label className="checkbox-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={!configured} /><span>I am authorized to send these redacted evidence excerpts to the configured Foundry project and understand that model usage may incur cost.</span></label>
        {error && <Notice title="Assessment not recorded" tone="error">{error}</Notice>}
      </div>
      <div className="modal-footer"><Button onClick={() => setOpen(false)} disabled={busy}>Cancel</Button><Button variant="primary" disabled={!configured || !confirmed || !incident || !can('workflow:run', incident.environment)} busy={busy} onClick={() => void assess()}><Bot size={18} />Request assessment</Button></div>
    </Modal>
  </>
}

export function Investigations() {
  const { data, setEvidenceFor, can } = useWorkspace()
  const incident = useIncident()
  const [tab, setTab] = useState('Assessment')
  const [selectedStage, setSelectedStage] = useState(8)
  if (!incident)
    return (
      <EmptyState
        title="No investigations"
        description="Create an incident and attach evidence to start an investigation."
      />
    )
  const evidence = data.evidence.filter(
    (record) => record.incidentId === incident.id
  )
  const hypotheses = data.hypotheses.filter(
    (record) => record.incidentId === incident.id
  )
  const leader = [...hypotheses].sort(
    (first, second) => second.confidence - first.confidence
  )[0]
  const currentStage = Math.min(
    14,
    stageIndex(incident.status) === 1 ? 8 : stageIndex(incident.status) + 8
  )
  return (
    <div className="page-enter">
      <PageHeader
        title="Root cause analysis"
        description="Structured evidence / Competing hypotheses / Human review"
        actions={<NextActionButton incident={incident} />}
      />
      <div className="module-context-bar">
        <IncidentSelector />
        <ModelAssessment />
        <Link className="text-link" to="/war-room">
          <Network size={15} />
          War Room
          <ArrowUpRight size={12} />
        </Link>
      </div>
      <div className="metrics-grid four">
        <Metric
          label="Evidence records"
          value={evidence.length.toString().padStart(2, '0')}
          detail={`${evidence.filter((record) => record.classification === 'Observed').length} observed / ${evidence.filter((record) => record.classification === 'Unverified').length} unverified`}
          icon={FileSearch}
        />
        <Metric
          label="Competing hypotheses"
          value={hypotheses.length.toString().padStart(2, '0')}
          detail="No conclusion from correlation alone"
          icon={Search}
        />
        <Metric
          label="Leading confidence"
          value={leader?.confidence.toFixed(2) ?? '--'}
          detail="Evidence strength, not causal proof"
          icon={CircleDot}
          critical
        />
        <Metric
          label="Missing observations"
          value={leader?.missing.length ?? '--'}
          detail="Additional validation required"
          icon={ListChecks}
        />
      </div>
      <div className="investigation-layout">
        <aside className="pipeline-sidebar">
          <div className="eyebrow">Investigation pipeline</div>
          <ol>
            {pipeline.map((stage, index) => (
              <li key={stage}>
                <button
                  className={`${index === selectedStage ? 'selected' : ''} ${index < currentStage ? 'done' : ''}`}
                  onClick={() => {
                    setSelectedStage(index)
                    setTab('Pipeline')
                  }}
                >
                  <span>
                    {index < currentStage ? (
                      <Check size={11} />
                    ) : (
                      String(index + 1).padStart(2, '0')
                    )}
                  </span>
                  <strong>{stage}</strong>
                </button>
              </li>
            ))}
          </ol>
          <div className="pipeline-mode">
            <FlaskConical size={14} />
            Synthetic workflow
          </div>
        </aside>
        <section className="investigation-main">
          <Tabs
            items={[
              'Assessment',
              'Evidence',
              'Validation criteria',
              'Pipeline',
            ]}
            value={tab}
            onChange={setTab}
          />
          {tab === 'Assessment' && (
            <>
              <SectionHeader
                title="Root-cause assessment"
                caption={`${incident.id} / ${incident.service}`}
                actions={<Badge>{leader?.status ?? 'Inconclusive'}</Badge>}
              />
              <HypothesisList incidentId={incident.id} />
              <div className="blast-radius">
                <SectionHeader
                  title="Potential blast radius"
                  caption="Based on the available topology snapshot"
                />
                <div className="blast-radius-services">
                  {[
                    incident.service,
                    ...data.dependencies
                      .filter((edge) => edge.source === incident.service)
                      .map((edge) => edge.target),
                  ].map((service) => (
                    <Link key={service} to={`/war-room?service=${service}`}>
                      <Network size={15} />
                      {service}
                      <ArrowUpRight size={12} />
                    </Link>
                  ))}
                </div>
              </div>
              <ProvenanceNote />
            </>
          )}
          {tab === 'Evidence' && (
            <>
              <SectionHeader
                title="Evidence provenance"
                caption="Observed, inferred and unverified records remain distinct"
                actions={
                  <Button
                    disabled={!can('evidence:add', incident.environment)}
                    onClick={() => setEvidenceFor(incident.id)}
                  >
                    Add evidence
                  </Button>
                }
              />
              <EvidenceList incidentId={incident.id} />
            </>
          )}
          {tab === 'Validation criteria' && (
            <>
              <SectionHeader
                title="Acceptance criteria"
                caption="Checkout scenario / proposed pool configuration"
              />
              <div className="criteria-list">
                {[
                  [
                    'Error rate',
                    'Below 1% over a 15-minute verification window',
                  ],
                  [
                    'Latency',
                    'Checkout p95 below 500 ms under equivalent load',
                  ],
                  [
                    'Connection budget',
                    'At most 150 application connections across five replicas; database limit 200',
                  ],
                  [
                    'Regression',
                    'Required checks pass for the exact proposed commit',
                  ],
                  [
                    'Security',
                    'No unresolved critical finding and a recorded security assessment',
                  ],
                  [
                    'Human governance',
                    'A different authorized human reviews the change and rollback plan',
                  ],
                ].map(([label, detail]) => (
                  <div key={label}>
                    <ShieldCheck size={17} />
                    <div>
                      <strong>{label}</strong>
                      <p>{detail}</p>
                    </div>
                  </div>
                ))}
              </div>
              <Notice title="Validation not implied by confidence">
                A plausible diagnosis is not a validated resolution. In this
                workspace, test replay and recovery observations are explicitly
                synthetic.
              </Notice>
              <Link className="button button-secondary" to="/testing">
                Open validation centre
                <ArrowRight size={14} />
              </Link>
            </>
          )}
          {tab === 'Pipeline' && (
            <>
              <SectionHeader
                title={pipeline[selectedStage]}
                caption={`Stage ${selectedStage + 1} of ${pipeline.length}`}
              />
              <Notice
                title={
                  selectedStage < currentStage
                    ? 'Available in the synthetic scenario'
                    : 'Pending workflow stage'
                }
              >
                {selectedStage < currentStage
                  ? 'The current demo snapshot includes observations for this stage. Inspect the linked evidence and persisted task history before drawing a conclusion.'
                  : 'This stage requires the preceding workflow evidence, required permissions and any configured approval gates.'}
              </Notice>
              <dl>
                <KeyValue label="Incident">{incident.id}</KeyValue>
                <KeyValue label="Execution state">
                  <Badge>{incident.workflowStatus}</Badge>
                </KeyValue>
                <KeyValue label="First observed">
                  {dateTime(incident.detectedAt)}
                </KeyValue>
                <KeyValue label="Responsible owner">{incident.owner}</KeyValue>
                <KeyValue label="Evidence scope">
                  {evidence.length} linked records
                </KeyValue>
                <KeyValue label="Model provider">
                  Not connected / deterministic demo replay
                </KeyValue>
              </dl>
              <h3 className="detail-section-title">Available source records</h3>
              <EvidenceList incidentId={incident.id} limit={3} />
              <Link className="button button-secondary" to="/agents">
                Inspect agent tasks
                <ArrowRight size={14} />
              </Link>
            </>
          )}
        </section>
      </div>
    </div>
  )
}

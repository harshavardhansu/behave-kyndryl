import { IncidentReportButton } from '../components/ReportPreview'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
} from '@xyflow/react'
import type { Edge, Node, NodeProps } from '@xyflow/react'
import {
  Activity,
  AppWindow,
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Boxes,
  Bot,
  CircleDot,
  Clock3,
  Cloud,
  CreditCard,
  Database,
  ExternalLink,
  Flag,
  GitBranch,
  Layers,
  Maximize,
  Network,
  Radio,
  RotateCcw,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  UserRound,
  X,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import type { Dependency, Service } from '../types'
import type { MissionView } from '../components/war-room/AgentCommandView'
import { MissionPanel } from '../components/war-room/MissionPanel'
import { PaymentSandboxPanel } from '../components/war-room/PaymentSandboxPanel'
import { latestMission, missionTeam, ROLE_NAMES, specialistCount } from '../lib/missions'
import { dateTime, elapsed, number, sla, time } from '../lib/format'
import '../components/war-room/war-room-3d.css'
import {
  Badge,
  Button,
  EmptyState,
  IconButton,
  KeyValue,
  Notice,
  PageHeader,
  SectionHeader,
  Select,
  Tabs,
  WorkflowSteps,
} from '../components/ui'
import {
  EventTimeline,
  EvidenceLinks,
  GateList,
  HypothesisList,
  IncidentSelector,
  NextActionButton,
  ProvenanceNote,
  WorkflowControls,
} from '../components/incident'

const AgentCommandView = lazy(() =>
  import('../components/war-room/AgentCommandView').then((module) => ({
    default: module.AgentCommandView,
  }))
)

/** The dependency map shows production topology; the isolated sandbox service is not part of it. */
// Connected projects (projects.json) have no recorded dependencies yet, so they are not drawn on the dependency map.
const topologyServices = (services: Service[]) => services.filter((service) => service.environment !== 'Sandbox' && !service.connected)

const serviceIcons = {
  Web: AppWindow,
  API: Network,
  Service: Boxes,
  Database,
  Cache: Layers,
  Queue: Server,
  Cloud,
  External: CreditCard,
}
type ServiceNode = Node<{ service: Service }, 'service'>

function ServiceGraphNode({ data, selected }: NodeProps<ServiceNode>) {
  const service = data.service
  const Icon = serviceIcons[service.type]
  return (
    <div
      className={`service-node ${service.health.toLowerCase()} ${selected ? 'node-selected' : ''}`}
    >
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
      <div className="service-node-main">
        <span className="service-node-icon">
          <Icon size={17} />
        </span>
        <div>
          <strong>{service.name}</strong>
          <span>
            {service.type === 'External' ? 'External dependency' : service.type}
          </span>
        </div>
        <i className={`node-health-dot ${service.health.toLowerCase()}`} />
      </div>
      <div className="service-node-metrics">
        <span>
          <Activity size={9} />
          {number(service.latency)}
          <small>ms</small>
        </span>
        <span
          className={service.health === 'Critical' ? 'node-error-value' : ''}
        >
          {service.errorRate}
          <small>% err</small>
        </span>
      </div>
    </div>
  )
}

const nodeTypes = { service: ServiceGraphNode }

function Topology({
  onService,
  onDependency,
  selectedId,
}: {
  onService: (service: Service) => void
  onDependency: (dependency: Dependency) => void
  selectedId: string | null
}) {
  const { data } = useWorkspace()
  const incident = useIncident()
  const flow = useReactFlow<ServiceNode>()
  const [nodes, setNodes, onNodesChange] = useNodesState<ServiceNode>(
    topologyServices(data.services).map((service) => ({
      id: service.id,
      type: 'service',
      position: service.position,
      data: { service },
      ariaLabel: `${service.name}, ${service.health}, ${service.latency} milliseconds`,
    }))
  )
  const [query, setQuery] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [health, setHealth] = useState('All health states')
  const [type, setType] = useState('All service types')
  const [minimum, setMinimum] = useState(0)
  const [criticalOnly, setCriticalOnly] = useState(false)
  const [externals, setExternals] = useState(true)
  useEffect(() => {
    setNodes((previous) =>
      topologyServices(data.services).map((service) => ({
        id: service.id,
        type: 'service',
        position:
          previous.find((node) => node.id === service.id)?.position ??
          service.position,
        data: { service },
        ariaLabel: `${service.name}, ${service.health}, ${service.latency} milliseconds`,
      }))
    )
  }, [data.services, setNodes])
  const criticalIds = new Set(
    data.dependencies
      .filter((edge) => edge.critical)
      .flatMap((edge) => [edge.source, edge.target])
  )
  const visible = nodes.filter(
    (node) =>
      (health === 'All health states' || node.data.service.health === health) &&
      (type === 'All service types' || node.data.service.type === type) &&
      (externals || node.data.service.type !== 'External') &&
      (!criticalOnly || criticalIds.has(node.id))
  )
  const visibleIds = new Set(visible.map((node) => node.id))
  const edges: Edge[] = data.dependencies
    .filter(
      (edge) =>
        visibleIds.has(edge.source) &&
        visibleIds.has(edge.target) &&
        edge.strength >= minimum &&
        (!criticalOnly || edge.critical)
    )
    .map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      animated: false,
      label: `${edge.strength.toFixed(2)}${edge.classification === 'Inferred' ? ' inferred' : ''}`,
      style: {
        stroke: edge.critical ? '#F5362A' : '#C7CBCF',
        strokeWidth: edge.critical ? 1.8 : 1.2,
        strokeDasharray: edge.classification === 'Inferred' ? '4 4' : undefined,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: edge.critical ? '#F5362A' : '#B4B9BF',
        width: 14,
        height: 14,
      },
      labelStyle: { fill: '#70767D', fontSize: 9, fontFamily: 'IBM Plex Mono' },
      labelBgStyle: { fill: '#FFFFFF', stroke: '#E8EAEC', strokeWidth: 0.6 },
      labelBgPadding: [4, 3],
      labelBgBorderRadius: 3,
      ariaLabel: `${edge.source} to ${edge.target}, ${edge.classification}, evidence strength ${edge.strength}`,
    }))

  function reset() {
    setNodes(
      topologyServices(data.services).map((service) => ({
        id: service.id,
        type: 'service',
        position: service.position,
        data: { service },
      }))
    )
    setQuery('')
    setHealth('All health states')
    setType('All service types')
    setMinimum(0)
    setCriticalOnly(false)
    setExternals(true)
    requestAnimationFrame(() => {
      void flow.fitView({ padding: 0.12, duration: 300 })
    })
  }

  function searchService() {
    const node = nodes.find((item) =>
      item.data.service.name.toLowerCase().includes(query.toLowerCase())
    )
    if (node) {
      onService(node.data.service)
      void flow.setCenter(node.position.x + 76, node.position.y + 42, {
        zoom: 1,
        duration: 400,
      })
    }
  }

  return (
    <div className="topology-workspace">
      <div className="topology-toolbar">
        <div className="graph-search">
          <Search size={14} />
          <input
            aria-label="Search graph services"
            placeholder="Find a service..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && query) searchService()
            }}
          />
          {query && (
            <button
              aria-label="Clear graph search"
              onClick={() => setQuery('')}
            >
              <X size={12} />
            </button>
          )}
        </div>
        <div className="topology-toolbar-actions">
          <IconButton
            label="Graph filters"
            aria-pressed={showFilters}
            onClick={() => setShowFilters(!showFilters)}
          >
            <SlidersHorizontal size={15} />
          </IconButton>
          <IconButton
            label="Fit graph to screen"
            onClick={() => void flow.fitView({ padding: 0.12, duration: 300 })}
          >
            <Maximize size={15} />
          </IconButton>
          <IconButton label="Reset graph layout" onClick={reset}>
            <RotateCcw size={15} />
          </IconButton>
        </div>
      </div>
      {showFilters && (
        <div className="graph-filters">
          <Select
            label="Graph health filter"
            value={health}
            onChange={(event) => setHealth(event.target.value)}
          >
            {['All health states', 'Healthy', 'Degraded', 'Critical'].map(
              (value) => (
                <option key={value}>{value}</option>
              )
            )}
          </Select>
          <Select
            label="Graph service type"
            value={type}
            onChange={(event) => setType(event.target.value)}
          >
            {['All service types', ...Object.keys(serviceIcons)].map(
              (value) => (
                <option key={value}>{value}</option>
              )
            )}
          </Select>
          <label className="range-label">
            Evidence strength <output>{minimum.toFixed(2)}+</output>
            <input
              aria-label="Minimum evidence strength"
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={minimum}
              onChange={(event) => setMinimum(Number(event.target.value))}
            />
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={criticalOnly}
              onChange={(event) => setCriticalOnly(event.target.checked)}
            />
            Critical path
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={externals}
              onChange={(event) => setExternals(event.target.checked)}
            />
            External dependencies
          </label>
        </div>
      )}
      <div
        className="graph-canvas"
        aria-label="Interactive service dependency graph"
      >
        {incident?.environment !== 'Production' ? (
          <EmptyState
            title="No topology snapshot for this environment"
            description={`The available catalog snapshot is Production only. ${incident?.environment ?? 'This environment'} telemetry is not configured.`}
            icon={Network}
          />
        ) : (
          <ReactFlow<ServiceNode>
            nodes={visible.map((node) => ({
              ...node,
              selected: node.id === selectedId,
              style: {
                opacity:
                  query &&
                    !node.data.service.name
                      .toLowerCase()
                      .includes(query.toLowerCase())
                    ? 0.25
                    : 1,
              },
            }))}
            edges={edges}
            onNodesChange={onNodesChange}
            nodeTypes={nodeTypes}
            onNodeClick={(_, node) => onService(node.data.service)}
            onEdgeClick={(_, edge) => {
              const selected = data.dependencies.find(
                (record) => record.id === edge.id
              )
              if (selected) onDependency(selected)
            }}
            fitView
            fitViewOptions={{ padding: 0.12 }}
            minZoom={0.3}
            maxZoom={2.2}
            nodesConnectable={false}
            elementsSelectable
            colorMode="light"
            defaultEdgeOptions={{ interactionWidth: 18 }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={18}
              size={0.8}
              color="#DADDE0"
            />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap
              pannable
              zoomable
              nodeColor={(node) =>
                (node.data.service as Service).health === 'Critical'
                  ? '#F5362A'
                  : '#D8DBDE'
              }
              nodeStrokeWidth={0}
              maskColor="#FFFFFFA8"
              position="bottom-right"
            />
          </ReactFlow>
        )}
        {!visible.length && incident?.environment === 'Production' && (
          <div className="graph-empty">
            <EmptyState
              title="No matching services"
              description="No service matches the selected graph filters."
              action={<Button onClick={reset}>Reset filters</Button>}
            />
          </div>
        )}
      </div>
      <div className="graph-legend">
        <span>
          <i className="node-health-dot healthy" />
          Healthy
        </span>
        <span>
          <i className="node-health-dot degraded" />
          Degraded
        </span>
        <span>
          <i className="node-health-dot critical" />
          Critical
        </span>
        <span>
          <i className="inferred-line" />
          Inferred
        </span>
        <span className="graph-legend-confidence">
          0.00-1.00 evidence strength
        </span>
      </div>
    </div>
  )
}

function ServiceInspector({ service }: { service: Service }) {
  const { data, selectIncident } = useWorkspace()
  const Icon = serviceIcons[service.type]
  return (
    <div className="service-inspector">
      <div className="inspector-identity">
        <span>
          <Icon size={22} />
        </span>
        <div>
          <h3>{service.name}</h3>
          <small>
            {service.type} / {service.environment}
          </small>
        </div>
      </div>
      <Badge>{service.health}</Badge>
      <div className="inspector-metrics">
        <div>
          <span>p95 latency</span>
          <strong>
            {number(service.latency)}
            <small> ms</small>
          </strong>
        </div>
        <div>
          <span>Error rate</span>
          <strong>
            {service.errorRate}
            <small>%</small>
          </strong>
        </div>
        <div>
          <span>Throughput</span>
          <strong>
            {number(service.rps)}
            <small> rps</small>
          </strong>
        </div>
      </div>
      <h4>Evidence sources</h4>
      <EvidenceLinks ids={service.evidence} />
      <h4>Open incidents</h4>
      {service.incidents.length ? (
        service.incidents.map((id) => (
          <Link
            className="inspector-link"
            key={id}
            to={`/incidents/${id}`}
            onClick={() => selectIncident(id)}
          >
            <span className="mono">{id}</span>
            <ArrowUpRight size={13} />
          </Link>
        ))
      ) : (
        <p className="muted">No linked incident in the snapshot.</p>
      )}
      <h4>Recent changes</h4>
      {service.changes.length ? (
        service.changes.map((id) => {
          const deployment = data.deployments.find((record) => record.id === id)
          return (
            <Link key={id} to="/changes" className="inspector-link">
              <GitBranch size={13} />
              <span>{deployment?.version ?? id}</span>
              <ArrowUpRight size={13} />
            </Link>
          )
        })
      ) : (
        <p className="muted">No recent change evidence.</p>
      )}
      <dl>
        <KeyValue label="Last observed">{time(service.observedAt)}</KeyValue>
        <KeyValue label="Source">Synthetic topology snapshot</KeyValue>
      </dl>
    </div>
  )
}

function DependencyInspector({ dependency }: { dependency: Dependency }) {
  return (
    <div className="dependency-inspector">
      <div className="edge-endpoints">
        <span>{dependency.source}</span>
        <ArrowDown size={17} />
        <span>{dependency.target}</span>
      </div>
      <div className="detail-badges">
        <Badge>{dependency.classification}</Badge>
        <Badge tone="outline">{dependency.strength.toFixed(2)} strength</Badge>
      </div>
      <dl>
        <KeyValue label="Relationship">{dependency.relationship}</KeyValue>
        <KeyValue label="Latency">{dependency.latency} ms</KeyValue>
        <KeyValue label="Affected path">
          {dependency.critical
            ? 'Observed error propagation'
            : 'Not on the selected critical path'}
        </KeyValue>
        <KeyValue label="Last observed">{time(dependency.timestamp)}</KeyValue>
      </dl>
      <h4>Supporting evidence</h4>
      <EvidenceLinks ids={dependency.evidence} />
      <Notice
        title={
          dependency.classification === 'Inferred'
            ? 'Inferred dependency'
            : 'Observed relationship'
        }
      >
        {dependency.classification === 'Inferred'
          ? 'This relationship is inferred from configuration in the synthetic snapshot. It has not been confirmed by a matching trace.'
          : 'The sample records support this relationship. A dependency or correlated failure does not establish a causal root cause.'}
      </Notice>
    </div>
  )
}

export function WarRoom() {
  const incident = useIncident()
  const [params] = useSearchParams()
  return <WarRoomWorkspace key={`${incident?.id}:${params.toString()}`} />
}

function WarRoomWorkspace() {
  const { data, can, setActionDialog, setEvidenceFor } =
    useWorkspace()
  const incident = useIncident()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [inspector, setInspector] = useState(params.get('agent') ? 'Agent' : params.get('edge') ? 'Dependency' : params.get('service') ? 'Service' : 'Findings')
  const [serviceId, setServiceId] = useState<string | null>(
    params.get('service')
  )
  const [dependencyId, setDependencyId] = useState<string | null>(
    params.get('edge')
  )
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(params.get('agent'))
  const [visualization, setVisualization] = useState<'workforce' | 'topology'>('workforce')
  const inspectorRef = useRef<HTMLElement>(null)
  if (!incident)
    return (
      <EmptyState
        title="No incident selected"
        description="Create an incident to open an operational workspace."
      />
    )
  const selectedService = data.services.find(
    (service) => service.id === serviceId
  )
  const selectedDependency = data.dependencies.find(
    (edge) => edge.id === dependencyId
  )
  const incidentAgents = data.agents.filter((agent) => agent.incidentId === incident.id)
  const mission = latestMission(data.missions, incident.id)
  const { iteration: missionIteration, caption: missionCaption, agents: missionAgents, proposed: proposedTeam } = missionTeam(incident, mission, data.missionSteps)
  const missionView: MissionView = {
    caption: missionCaption,
    running: mission?.status === 'Analysing' || mission?.status === 'Working',
    skipped: (missionIteration?.team.length ? missionIteration.skipped : missionIteration?.plan?.skipped ?? []).map((item) => ({
      role: item.role, name: ROLE_NAMES[item.role] ?? item.role, reason: item.reason,
    })),
    fixApproved: Boolean(missionIteration?.decisions.some((decision) => decision.type === 'fix' && decision.decision === 'approve')),
    hasMission: Boolean(missionIteration?.team.length || proposedTeam.length),
  }
  const selectedAgent = missionAgents.find((agent) => agent.id === selectedAgentId)
  const activeApproval = data.approvals
    .filter((approval) => approval.incidentId === incident.id)
    .sort((left, right) => right.requestedAt.localeCompare(left.requestedAt))[0]
  const foundry = data.integrations.find((integration) => integration.id === 'foundry')
  const aiActive = (mission?.mode ?? data.aiMode ?? '').startsWith('AI-GENERATED')
  const agentExecutionLabel = aiActive ? 'AI-GENERATED' : data.mode === 'demo' ? 'SIMULATED' : 'NOT CONFIGURED'
  const providerLabel = data.aiMode?.startsWith('AI-GENERATED')
    ? `${data.aiMode.split(' / ')[1] ?? 'Azure OpenAI'}${foundry?.authentication ? ` (${foundry.authentication})` : ''}`
    : foundry?.status === 'Not configured'
      ? 'NOT CONFIGURED'
      : 'NOT CONFIGURED / connection not verified'
  const firstTaskStart = incidentAgents
    .map((agent) => agent.startedAt)
    .filter((value): value is string => Boolean(value))
    .sort()[0]
  const taskDuration = firstTaskStart
    ? elapsed(firstTaskStart, data.snapshotAt)
    : 'Not started'
  const affected = data.services.find(
    (service) => service.id === incident.service
  )
  const change = data.changes.find(
    (record) => record.incidentId === incident.id
  )
  const incidentEvidence = data.evidence.filter(
    (record) => record.incidentId === incident.id
  )
  const selectedAgentEvidenceIds = selectedAgent
    ? [...new Set([...selectedAgent.inputs, ...selectedAgent.outputs])].filter(
      (id) => incidentEvidence.some((record) => record.id === id)
    )
    : []
  const logs = data.logs
    .filter((record) =>
      incidentEvidence.some((item) => item.id === record.evidenceId)
    )
    .slice(0, 3)
  const deployments = data.deployments.filter(
    (record) => record.service === incident.service
  )
  return (
    <div className="war-room-page page-enter">
      <PageHeader
        title="AI War Room"
        description="Incident operations / Evidence-led response"
        actions={
          <>
            <IncidentReportButton incidentId={incident.id} />
            <NextActionButton incident={incident} />
          </>
        }
      />
      <div className="war-scope-row">
        <IncidentSelector />
        <div className="war-scope-meta">
          <span className="snapshot-mode"><CircleDot size={13} /> {agentExecutionLabel} / backend task snapshot</span>
          <span className="snapshot-mode">Updated {time(data.snapshotAt)}</span>
          <span className="snapshot-mode">Provider {providerLabel}</span>
        </div>
      </div>
      <div className="war-incident-header">
        <div className="war-incident-title">
          <Badge tone="critical" dot={false}>
            {incident.severity === 'Critical' ? 'P1' : incident.severity}
          </Badge>
          <div>
            <Link to={`/incidents/${incident.id}`}>
              <span className="mono">{incident.id}</span>
              <ArrowUpRight size={12} />
            </Link>
            <h2>{incident.title}</h2>
          </div>
        </div>
        <div className="war-incident-facts">
          <div>
            <span>Environment</span>
            <strong>
              <i className="environment-dot" />
              {incident.environment}
            </strong>
          </div>
          <div>
            <span>Duration</span>
            <strong>{elapsed(incident.detectedAt, data.snapshotAt)}</strong>
          </div>
          <div>
            <span>Workflow</span>
            <strong>{incident.workflowStatus}</strong>
          </div>
          <div>
            <span>Workflow ID</span>
            <strong>Not recorded</strong>
          </div>
          <div>
            <span>Task duration</span>
            <strong>{taskDuration}</strong>
          </div>
          <div>
            <span>Approval</span>
            <strong>{activeApproval?.status ?? 'No request'}</strong>
          </div>
          <div>
            <span>Commander</span>
            <button
              onClick={() =>
                setActionDialog({ incidentId: incident.id, action: 'assign' })
              }
              disabled={!can('incident:update', incident.environment)}
            >
              {incident.commander}
              <UserRound size={12} />
            </button>
          </div>
          <div className="sla-fact">
            <span>SLA window</span>
            <strong>
              <Clock3 size={13} />
              {sla(incident, data.snapshotAt).label}
            </strong>
          </div>
        </div>
      </div>
      <WorkflowSteps status={incident.status} />
      <div className={`war-main-grid ${visualization === 'workforce' ? 'command-mode' : ''}`}>
        <aside className="war-context">
          <div className="war-panel-heading">
            <h3>Incident context</h3>
            <Badge tone="outline" dot={false}>
              {incident.status}
            </Badge>
          </div>
          <section>
            <span className="war-label">Business impact</span>
            <p>{incident.impact}</p>
          </section>
          <section>
            <span className="war-label">Affected service</span>
            <button
              className="affected-service-button"
              onClick={() => {
                if (affected) {
                  setServiceId(affected.id)
                  setInspector('Service')
                }
              }}
              disabled={!affected}
            >
              <Boxes size={16} />
              <strong>{incident.service}</strong>
              <ChevronMark />
            </button>
            {affected && (
              <div className="context-metrics">
                <div>
                  <span>Error rate</span>
                  <strong>{affected.errorRate}%</strong>
                </div>
                <div>
                  <span>p95 latency</span>
                  <strong>
                    {number(affected.latency)}
                    <small> ms</small>
                  </strong>
                </div>
              </div>
            )}
          </section>
          <section>
            <span className="war-label">Detection</span>
            <div className="context-detail">
              <Radio size={13} />
              <span>{incident.source}</span>
            </div>
            <div className="context-detail">
              <Clock3 size={13} />
              <span>{dateTime(incident.detectedAt)}</span>
            </div>
          </section>
          <section>
            <span className="war-label">Recent changes</span>
            {deployments.slice(0, 2).map((deployment) => (
              <Link
                className="context-change"
                key={deployment.id}
                to="/changes"
              >
                <GitBranch size={14} />
                <div>
                  <strong>{deployment.version}</strong>
                  <span>
                    {time(deployment.timestamp)} / {deployment.environment}
                  </span>
                </div>
                <ArrowUpRight size={12} />
              </Link>
            ))}
            {!deployments.length && <p>No recent deployment evidence.</p>}
          </section>
          <section>
            <span className="war-label">Known symptom</span>
            <p className="context-error">{incident.error}</p>
          </section>
          <div className="context-actions">
            <Button
              onClick={() => setEvidenceFor(incident.id)}
              disabled={!can('evidence:add', incident.environment)}
            >
              <Upload size={13} />
              Add evidence
            </Button>
            <Button
              onClick={() =>
                setActionDialog({ incidentId: incident.id, action: 'escalate' })
              }
              disabled={!can('incident:update', incident.environment)}
            >
              <Flag size={13} />
              Escalate
            </Button>
          </div>
        </aside>
        <section className={`war-topology ${visualization === 'workforce' ? 'workforce-center-panel' : ''}`}>
          <div className="war-panel-heading workforce-panel-heading">
            <div>
              <h3>
                {visualization === 'workforce' ? <Bot size={16} /> : <Network size={16} />}
                {visualization === 'workforce' ? 'AI specialist workforce' : 'Service dependency graph'}
              </h3>
              <span>
                {visualization === 'workforce'
                  ? mission
                    ? `${missionAgents.length - 1} of ${specialistCount(data.missionSteps)} specialists in ${mission.id} / iteration ${mission.iteration}`
                    : 'The Orchestrator forms a team per ticket'
                  : `${topologyServices(data.services).length} services / ${data.dependencies.length} relationships`}
              </span>
            </div>
            <div className="war-view-switch" role="group" aria-label="War Room visualization">
              <button type="button" aria-pressed={visualization === 'workforce'} onClick={() => setVisualization('workforce')}><Bot size={13} /> Workforce</button>
              <button type="button" aria-pressed={visualization === 'topology'} onClick={() => setVisualization('topology')}><Network size={13} /> XY Flow</button>
            </div>
          </div>
          {visualization === 'topology' && incident.id !== 'INC-1042' && (
            <div className="catalog-warning">
              Shared catalog snapshot; not correlated to this incident's time
              window.
            </div>
          )}
          {visualization === 'workforce' ? (
            <>
              <div className="workforce-truth-row">
                <Badge tone="outline" dot={false}>{agentExecutionLabel}</Badge>
                <span>{mission ? `Mission ${mission.status}` : 'No mission yet'}</span>
                <span>{mission ? `${missionAgents.length - 1} of ${specialistCount(data.missionSteps)} specialists` : 'Team formed per ticket'}</span>
              </div>
              {incident.service === 'payment-api' && incident.environment === 'Sandbox' && <PaymentSandboxPanel incident={incident} />}
              <MissionPanel incident={incident} mission={mission} />
              <Suspense fallback={<div className="workforce-loading">Loading the agent command view…</div>}>
                <AgentCommandView
                  incident={incident}
                  agents={missionAgents}
                  mission={missionView}
                  steps={data.missionSteps}
                  evidence={incidentEvidence}
                  hypotheses={data.hypotheses.filter((hypothesis) => hypothesis.incidentId === incident.id)}
                  change={change}
                  approval={activeApproval}
                  selectedId={selectedAgent?.id ?? null}
                  onSelectEvidence={setEvidenceFor}
                  onSelect={(agent) => {
                    setSelectedAgentId(agent.id)
                    setInspector('Agent')
                  }}
                  onShowDetails={() => inspectorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                />
              </Suspense>
              <p className="workforce-integrity-note">
                {(mission?.mode ?? data.aiMode ?? '').startsWith('AI-GENERATED')
                  ? `Team selection, skip reasons, findings and outcomes are AI-generated by ${(mission?.mode ?? data.aiMode ?? '').split(' / ')[1] ?? 'Azure OpenAI'} under daily cost limits, then checked against the real specialist roles and evidence IDs. Agents investigate with read-only tools (evidence, logs, service status, changes, the repository and runbooks) and cannot change anything; only a fix a human approved is applied. Humans approve the team, the root cause, the fix and the outcome.`
                  : 'Team selection, skip reasons, findings and outcomes come from the free SIMULATED rule-based planner; no AI model or tool runs. Humans approve the team, the root cause, the fix and the outcome.'}
              </p>
            </>
          ) : (
            <ReactFlowProvider>
              <Topology
                selectedId={serviceId}
                onService={(service) => {
                  setServiceId(service.id)
                  setInspector('Service')
                }}
                onDependency={(edge) => {
                  setDependencyId(edge.id)
                  setInspector('Dependency')
                }}
              />
            </ReactFlowProvider>
          )}
        </section>
        <aside className="war-findings" ref={inspectorRef}>
          <Tabs
            items={[
              'Findings',
              ...(selectedAgent ? ['Agent'] : []),
              ...(selectedService ? ['Service'] : []),
              ...(selectedDependency ? ['Dependency'] : []),
            ]}
            value={inspector}
            onChange={setInspector}
          />
          <div className="war-inspector-body">
            {inspector === 'Findings' && (
              <>
                <div className="findings-summary">
                  <span className="eyebrow">Leading hypotheses</span>
                  <Badge tone="outline" dot={false}>
                    {
                      data.hypotheses.filter(
                        (record) => record.incidentId === incident.id
                      ).length
                    }{' '}
                    candidates
                  </Badge>
                </div>
                <HypothesisList incidentId={incident.id} compact />
                <div className="next-diagnostic">
                  <span className="war-label">Recommended diagnostic</span>
                  <p>
                    {data.hypotheses.find(
                      (record) => record.incidentId === incident.id
                    )?.nextStep ??
                      'Collect service logs and an incident-correlated metrics window.'}
                  </p>
                  <Link className="text-link" to="/investigations">
                    Full assessment
                    <ArrowRight size={12} />
                  </Link>
                </div>
                <ProvenanceNote />
              </>
            )}
            {inspector === 'Agent' && selectedAgent && (
              <div className="workforce-agent-inspector">
                <div className="inspector-identity">
                  <span><Bot size={22} /></span>
                  <div><h3>{selectedAgent.name}</h3><small>{selectedAgent.role}</small></div>
                </div>
                <Badge>{selectedAgent.status}</Badge>
                <p className="body-copy">{selectedAgent.purpose}</p>
                <dl>
                  <KeyValue label="Agent ID" mono>{selectedAgent.id}</KeyValue>
                  <KeyValue label="Current task">{selectedAgent.task}</KeyValue>
                  <KeyValue label="Started">{dateTime(selectedAgent.startedAt)}</KeyValue>
                  <KeyValue label="Last update">{dateTime(selectedAgent.lastActivity)}</KeyValue>
                  <KeyValue label="Retries">{selectedAgent.retries} / {data.policy.maxRetries}</KeyValue>
                  <KeyValue label="Model usage">{selectedAgent.usage ?? 'Not measured / no model invocation'}</KeyValue>
                  <KeyValue label="Human approval">{selectedAgent.approvalRequired ? activeApproval?.status ?? 'No approval record' : 'Not required for this task'}</KeyValue>
                </dl>
                <h4>Declared task dependencies</h4>
                <div className="workforce-agent-dependencies">
                  {selectedAgent.dependencies.map((id) => {
                    const dependency = missionAgents.find((agent) => agent.id === id)
                    return dependency ? (
                      <button key={id} onClick={() => setSelectedAgentId(id)}>{dependency.name}<Badge>{dependency.status}</Badge></button>
                    ) : null
                  })}
                  {!selectedAgent.dependencies.some((id) => missionAgents.some((agent) => agent.id === id)) && <span className="muted">Hand-offs follow the mission steps: {(data.missionSteps ?? []).map((step) => step.name).join(', ') || 'Investigate, Diagnose, Remediate & validate, Govern & release'}.</span>}
                </div>
                <h4>Linked evidence</h4>
                <EvidenceLinks ids={selectedAgentEvidenceIds} />
                <Notice title="Execution boundary">{selectedAgent.limitations}</Notice>
                {incidentAgents.some((agent) => agent.id === selectedAgent.id) && <Link className="text-link" to={`/agents?task=${selectedAgent.id}`}>Open task record <ArrowUpRight size={12} /></Link>}
              </div>
            )}
            {inspector === 'Service' && selectedService && (
              <ServiceInspector service={selectedService} />
            )}
            {inspector === 'Dependency' && selectedDependency && (
              <DependencyInspector dependency={selectedDependency} />
            )}
          </div>
        </aside>
      </div>
      <div className="war-event-band">
        <EventTimeline incidentId={incident.id} compact />
      </div>
      <div className="war-lower-grid">
        <section className="workspace-section">
          <SectionHeader
            title="Log evidence"
            caption="Correlated source records"
            actions={
              <Link
                className="text-link"
                to={`/observability?service=${incident.service}`}
              >
                Explorer
                <ArrowUpRight size={12} />
              </Link>
            }
          />
          <div className="war-log-stream">
            {logs.map((log) => (
              <div key={log.id}>
                <time>{time(log.timestamp)}</time>
                <Badge>{log.level}</Badge>
                <p>{log.message}</p>
                <EvidenceLinks ids={[log.evidenceId]} />
              </div>
            ))}
            {!logs.length && (
              <EmptyState
                title="No correlated logs"
                description="Import evidence with source timestamps to populate this view."
              />
            )}
          </div>
        </section>
        <section className="workspace-section">
          <SectionHeader
            title="Agent execution"
            caption="Demo workflow / explicit control"
            actions={
              <Link
                to="/agents"
                className="icon-link"
                aria-label="Agent execution details"
              >
                <ArrowUpRight size={16} />
              </Link>
            }
          />
          <WorkflowControls incident={incident} />
          <div className="mini-agent-list">
            {data.agents
              .filter((agent) => agent.incidentId === incident.id)
              .slice(0, 5)
              .map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => navigate(`/agents?task=${agent.id}`)}
                >
                  <span>{agent.name}</span>
                  <Badge>{agent.status}</Badge>
                </button>
              ))}
          </div>
        </section>
        <section className="workspace-section">
          <SectionHeader
            title="Release readiness"
            caption={
              change
                ? `${change.id} / ${change.risk} risk`
                : 'No proposed change'
            }
            actions={
              <Link
                to="/changes"
                className="icon-link"
                aria-label="Change and approval details"
              >
                <ShieldCheck size={17} />
              </Link>
            }
          />
          {change ? (
            <>
              <Link className="remediation-link" to="/changes">
                <GitBranch size={16} />
                <strong>{change.title}</strong>
                <ExternalLink size={13} />
              </Link>
              <GateList gates={change.gates} />
              <Button
                className="full-width"
                onClick={() => navigate('/changes?view=Approvals')}
              >
                Open approval queue
                <ArrowRight size={14} />
              </Button>
            </>
          ) : (
            <EmptyState
              title="No remediation proposal"
              description="Complete a supported investigation before preparing a change."
            />
          )}
        </section>
      </div>
    </div>
  )
}

function ChevronMark() {
  return <ArrowUpRight size={12} />
}

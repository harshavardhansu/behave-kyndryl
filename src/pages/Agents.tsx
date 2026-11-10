import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Background, Controls, MarkerType, ReactFlow } from '@xyflow/react'
import type { Edge, Node } from '@xyflow/react'
import type { ColumnDef } from '@tanstack/react-table'
import {
  Activity,
  ArrowRight,
  Bot,
  CheckCheck,
  Clock3,
  GitBranch,
  LockKeyhole,
  ShieldCheck,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import type { Agent } from '../types'
import { dateTime } from '../lib/format'
import {
  Badge,
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
  EventTimeline,
  EvidenceLinks,
  IncidentSelector,
  WorkflowControls,
} from '../components/incident'

function CollaborationGraph({
  tasks,
  onSelect,
}: {
  tasks: Agent[]
  onSelect: (task: Agent) => void
}) {
  const groups = new Map<number, Agent[]>()
  tasks.forEach((task) =>
    groups.set(task.phase, [...(groups.get(task.phase) ?? []), task])
  )
  const nodes: Node[] = tasks.map((task) => ({
    id: task.id,
    position: {
      x: (task.phase + 1) * 195,
      y:
        (groups.get(task.phase)?.indexOf(task) ?? 0) * 95 +
        (4 - (groups.get(task.phase)?.length ?? 1)) * 45,
    },
    data: {
      label: (
        <div className="task-graph-node">
          <Bot size={16} />
          <strong>{task.name}</strong>
          <Badge dot={false}>{task.status}</Badge>
        </div>
      ),
    },
    className: task.status === 'Running' ? 'task-node-running' : '',
    style: {
      width: 168,
      border: `1px solid ${task.status === 'Running' ? '#F5362A' : '#DCDFE2'}`,
      background: '#FFFFFF',
      borderRadius: 5,
      padding: 11,
    },
    ariaLabel: `${task.name}, ${task.status}`,
  }))
  const edges: Edge[] = tasks.flatMap((task) =>
    task.dependencies
      .filter((dependency) => tasks.some((item) => item.id === dependency))
      .map((dependency) => ({
        id: `${dependency}-${task.id}`,
        source: dependency,
        target: task.id,
        type: 'smoothstep',
        style: { stroke: '#C8CDD2', strokeWidth: 1.3 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#B5BBC2' },
      }))
  )
  return (
    <div className="collaboration-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.13 }}
        nodesConnectable={false}
        onNodeClick={(_, node) => {
          const task = tasks.find((item) => item.id === node.id)
          if (task) onSelect(task)
        }}
        onEdgeClick={(_, edge) => {
          const task = tasks.find((item) => item.id === edge.target)
          if (task) onSelect(task)
        }}
        minZoom={0.3}
        maxZoom={2}
      >
        <Background color="#DADDE1" gap={18} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

export function Agents() {
  const { data } = useWorkspace()
  const incident = useIncident()
  const [params] = useSearchParams()
  const [tab, setTab] = useState('Task board')
  const [status, setStatus] = useState('All statuses')
  const [selectedId, setSelectedId] = useState<string | null>(
    params.get('task')
  )
  if (!incident) return <EmptyState title="No incident selected" />
  const tasks = data.agents.filter((agent) => agent.incidentId === incident.id)
  const selected = data.agents.find((task) => task.id === selectedId)
  const columns: ColumnDef<Agent>[] = [
    {
      accessorKey: 'name',
      header: 'Agent',
      cell: ({ row }) => (
        <div className="agent-table-name">
          <span className="agent-icon">
            <Bot size={17} />
          </span>
          <div>
            <strong>{row.original.name}</strong>
            <small>{row.original.role}</small>
          </div>
        </div>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    {
      accessorKey: 'task',
      header: 'Current task',
      cell: ({ getValue }) => (
        <span className="task-description">{String(getValue())}</span>
      ),
    },
    {
      id: 'dependencies',
      header: 'Dependencies',
      accessorFn: (task) => task.dependencies.length,
      cell: ({ getValue }) => (
        <span className="mono">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'lastActivity',
      header: 'Last activity',
      cell: ({ getValue }) => (
        <span className="table-timestamp">
          {dateTime(getValue() as string | null)}
        </span>
      ),
    },
    {
      accessorKey: 'retries',
      header: 'Retries',
      cell: ({ getValue }) => (
        <span className="mono">
          {String(getValue())} / {data.policy.maxRetries}
        </span>
      ),
    },
    {
      accessorKey: 'approvalRequired',
      header: 'Approval',
      cell: ({ getValue }) =>
        getValue() ? (
          <span className="permission-label">
            <LockKeyhole size={12} />
            Required
          </span>
        ) : (
          <span className="muted">Not required</span>
        ),
    },
  ]
  return (
    <div className="page-enter">
      <PageHeader
        title="Agent orchestration"
        description="Coordinated workers / Bounded tools / Persisted checkpoints"
        actions={<Badge tone="outline">Synthetic execution mode</Badge>}
      />
      <div className="module-context-bar">
        <IncidentSelector />
        <WorkflowControls incident={incident} />
      </div>
      <div className="metrics-grid four">
        <Metric
          label="Running"
          value={tasks
            .filter((task) => task.status === 'Running')
            .length.toString()
            .padStart(2, '0')}
          detail="Active synthetic tasks"
          icon={Activity}
          critical
        />
        <Metric
          label="Queued"
          value={tasks
            .filter((task) => task.status === 'Queued')
            .length.toString()
            .padStart(2, '0')}
          detail="Waiting on task dependencies"
          icon={Clock3}
        />
        <Metric
          label="Human decision"
          value={tasks
            .filter((task) => task.status === 'Waiting for Human Approval')
            .length.toString()
            .padStart(2, '0')}
          detail="Explicit approval required"
          icon={ShieldCheck}
        />
        <Metric
          label="Completed"
          value={tasks
            .filter((task) => task.status === 'Completed')
            .length.toString()
            .padStart(2, '0')}
          detail={`${tasks.length} specialized worker tasks`}
          icon={CheckCheck}
        />
      </div>
      <Tabs
        items={['Task board', 'Collaboration graph', 'Execution history']}
        value={tab}
        onChange={setTab}
      />
      {tab === 'Task board' && (
        <DataTable
          data={tasks.filter(
            (task) => status === 'All statuses' || task.status === status
          )}
          columns={columns}
          onRowClick={(task) => setSelectedId(task.id)}
          searchPlaceholder="Search agents or current tasks"
          pageSize={12}
          toolbar={
            <Select
              label="Agent status filter"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              {[
                'All statuses',
                'Idle',
                'Queued',
                'Running',
                'Waiting for Evidence',
                'Waiting for Human Approval',
                'Completed',
                'Failed',
                'Cancelled',
                'Paused',
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </Select>
          }
          emptyTitle="No matching tasks"
          emptyDescription="No task is available for this incident and status filter."
        />
      )}
      {tab === 'Collaboration graph' && (
        <>
          <SectionHeader
            title="Task dependency graph"
            caption="Parallel analysis branches converge before a remediation proposal"
            actions={<Badge>{incident.workflowStatus}</Badge>}
          />
          {tasks.length ? (
            <CollaborationGraph
              tasks={tasks}
              onSelect={(task) => setSelectedId(task.id)}
            />
          ) : (
            <EmptyState
              title="No workflow graph"
              description="An investigation has not been started for this incident."
            />
          )}
          <Notice title="Execution policy">
            Evidence-only deterministic demo workers have no shell, network
            tools or production write access. Independent context tasks share a
            phase; later phases wait for their inputs.
          </Notice>
        </>
      )}
      {tab === 'Execution history' && (
        <EventTimeline incidentId={incident.id} />
      )}
      <div className="execution-budget">
        <div>
          <Clock3 size={16} />
          <span>
            Task budget<strong>{data.policy.maxTaskSeconds}s</strong>
          </span>
        </div>
        <div>
          <GitBranch size={16} />
          <span>
            Retry budget<strong>{data.policy.maxRetries} attempts</strong>
          </span>
        </div>
        <div>
          <LockKeyhole size={16} />
          <span>
            Tool permissions<strong>Read-only fixture data</strong>
          </span>
        </div>
        <div>
          <Bot size={16} />
          <span>
            Token usage<strong>Not available / no model calls</strong>
          </span>
        </div>
      </div>
      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelectedId(null)}
        title={selected?.name ?? 'Agent task'}
        subtitle="Structured task output"
      >
        {selected && (
          <>
            <div className="detail-badges">
              <Badge>{selected.status}</Badge>
              <Badge tone="outline">Demo worker</Badge>
            </div>
            <p className="body-copy">{selected.purpose}</p>
            <dl>
              <KeyValue label="Task ID" mono>
                {selected.id}
              </KeyValue>
              <KeyValue label="Incident">
                <Link
                  className="text-link"
                  to={`/incidents/${selected.incidentId}`}
                >
                  {selected.incidentId}
                  <ArrowRight size={13} />
                </Link>
              </KeyValue>
              <KeyValue label="Current task">{selected.task}</KeyValue>
              <KeyValue label="Started">
                {dateTime(selected.startedAt)}
              </KeyValue>
              <KeyValue label="Last activity">
                {dateTime(selected.lastActivity)}
              </KeyValue>
              <KeyValue label="Retry count">
                {selected.retries} / {data.policy.maxRetries}
              </KeyValue>
              <KeyValue label="Usage">
                {selected.usage ?? 'Not measured; no model invocation'}
              </KeyValue>
              <KeyValue label="Approval">
                {selected.approvalRequired
                  ? 'Separate human approval required'
                  : 'Not required for this bounded task'}
              </KeyValue>
            </dl>
            <h3 className="detail-section-title">Input evidence</h3>
            <EvidenceLinks
              ids={selected.inputs.filter((id) =>
                data.evidence.some((record) => record.id === id)
              )}
            />
            <h3 className="detail-section-title">Output artifacts</h3>
            <div className="artifact-list">
              {selected.outputs.map((id) => (
                <div key={id}>
                  <FileArtifact />
                  <span className="mono">{id}</span>
                </div>
              ))}
              {!selected.outputs.length && (
                <p className="muted">No outputs recorded yet.</p>
              )}
            </div>
            <h3 className="detail-section-title">Task dependencies</h3>
            <div className="task-dependencies">
              {selected.dependencies.map((id) => (
                <button key={id} onClick={() => setSelectedId(id)}>
                  {data.agents.find((task) => task.id === id)?.name ?? id}
                  <ArrowRight size={12} />
                </button>
              ))}
              {!selected.dependencies.length && (
                <span className="muted">No upstream task dependency.</span>
              )}
            </div>
            <Notice title="Execution limitations">
              {selected.limitations}
            </Notice>
          </>
        )}
      </Drawer>
    </div>
  )
}

function FileArtifact() {
  return <CheckCheck size={13} />
}

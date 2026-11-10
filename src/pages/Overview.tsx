import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Bot,
  CalendarDays,
  CheckCheck,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileCheck2,
  GitPullRequest,
  Network,
  Plus,
  RefreshCw,
  ShieldCheck,
  Timer,
  TriangleAlert,
  Zap,
} from 'lucide-react'
import type { ColumnDef } from '@tanstack/react-table'
import { useWorkspace } from '../context'
import {
  closedStatuses,
  dateTime,
  severityRank,
  sla,
  time,
} from '../lib/format'
import type { Incident } from '../types'
import {
  Avatar,
  Badge,
  Button,
  DataTable,
  EmptyState,
  IconButton,
  Metric,
  PageHeader,
  SectionHeader,
  Select,
} from '../components/ui'

export function Overview() {
  const {
    data,
    environment,
    selectIncident,
    setCreateOpen,
    can,
    refresh,
    refreshing,
  } = useWorkspace()
  const navigate = useNavigate()
  const [service, setService] = useState('All services')
  const [period, setPeriod] = useState('24 hours')
  const cutoff =
    new Date(data.snapshotAt).getTime() -
    (period === '24 hours' ? 1 : period === '7 days' ? 7 : 30) * 86_400_000
  const incidents = data.incidents.filter(
    (incident) =>
      incident.environment === environment &&
      (service === 'All services' || incident.service === service) &&
      new Date(incident.detectedAt).getTime() >= cutoff
  )
  const open = incidents.filter(
    (incident) => !closedStatuses.includes(incident.status)
  )
  const critical = open.filter((incident) => incident.severity === 'Critical')
  const investigating = open.filter((incident) =>
    ['Investigating', 'Root Cause Identified'].includes(incident.status)
  )
  const pending = data.approvals.filter(
    (approval) =>
      approval.status === 'Pending' &&
      incidents.some((incident) => incident.id === approval.incidentId)
  )
  const services = data.services.filter(
    (record) =>
      record.environment === environment &&
      (service === 'All services' || record.id === service)
  )
  const health = ['Healthy', 'Degraded', 'Critical'].map((name) => ({
    name,
    value: services.filter((record) => record.health === name).length,
  }))
  const attention = [...critical, ...open][0]
  const tasks = data.agents.filter((agent) =>
    incidents.some((incident) => incident.id === agent.incidentId)
  )
  const completedTasks = tasks.filter(
    (task) => task.status === 'Completed'
  ).length
  const active = [...open].sort(
    (first, second) =>
      severityRank[first.severity] - severityRank[second.severity]
  )
  const relevantTests = data.tests.filter((test) =>
    incidents.some((incident) => incident.id === test.incidentId)
  )
  const passed = relevantTests.reduce((total, test) => total + test.passed, 0)
  const failed = relevantTests.reduce((total, test) => total + test.failed, 0)
  const slaRisk = open.filter((incident) => sla(incident, data.snapshotAt).risk)
  const columns: ColumnDef<Incident>[] = [
    {
      accessorKey: 'title',
      header: 'Incident',
      cell: ({ row }) => (
        <div className="incident-cell">
          <span className="mono record-id">{row.original.id}</span>
          <strong>{row.original.title}</strong>
          <small>{row.original.service}</small>
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
      accessorKey: 'owner',
      header: 'Owner',
      cell: ({ getValue }) => <Avatar small name={String(getValue())} />,
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
  ]
  function openIncident(incident: Incident) {
    selectIncident(incident.id)
    navigate(`/incidents/${incident.id}`)
  }
  return (
    <div className="overview-page page-enter">
      <PageHeader
        title="Command centre"
        description={`${environment} operations / ${new Date(data.snapshotAt).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}`}
        actions={
          <>
            <IconButton
              label="Refresh workspace"
              onClick={() => void refresh()}
            >
              <RefreshCw size={17} className={refreshing ? 'spin' : ''} />
            </IconButton>
            <Button
              variant="primary"
              disabled={!can('incident:create', environment)}
              onClick={() => setCreateOpen(true)}
            >
              <Plus size={19} />
              Create incident
            </Button>
          </>
        }
      />
      <div className="overview-toolbar">
        <div className="scope-label">
          <span className="live-dot" />
          Operations overview
          <span className="scope-divider" />
          {incidents.length} incident records
        </div>
        <div className="filter-row">
          <Select
            label="Service filter"
            value={service}
            onChange={(event) => setService(event.target.value)}
          >
            <option>All services</option>
            {data.services.map((record) => (
              <option key={record.id} value={record.id}>
                {record.name}
              </option>
            ))}
          </Select>
          <div className="date-filter">
            <CalendarDays size={15} />
            <Select
              label="Overview time range"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
            >
              <option>24 hours</option>
              <option>7 days</option>
              <option>30 days</option>
            </Select>
          </div>
        </div>
      </div>
      <div className="metrics-grid four">
        <Metric
          label="Open incidents"
          value={open.length.toString().padStart(2, '0')}
          detail={`${environment} / last ${period}`}
          icon={TriangleAlert}
          trend={[28, 44, 35, 60, 38, 70, 50, 42, 63, 54, 74, 59]}
          onClick={() =>
            navigate(
              `/incidents?status=open&service=${service === 'All services' ? '' : service}`
            )
          }
        />
        <Metric
          label="Critical incidents"
          value={critical.length.toString().padStart(2, '0')}
          detail={`${slaRisk.length} incident${slaRisk.length === 1 ? '' : 's'} at SLA risk`}
          icon={CircleAlert}
          critical
          trend={[20, 20, 38, 20, 20, 50, 30, 30, 65, 50, 75, 58]}
          onClick={() => navigate('/incidents?severity=Critical')}
        />
        <Metric
          label="Active investigations"
          value={investigating.length.toString().padStart(2, '0')}
          detail={`${tasks.filter((task) => task.status === 'Running').length} agents currently running`}
          icon={Activity}
          trend={[40, 30, 50, 40, 55, 60, 40, 65, 50, 76, 65, 80]}
          onClick={() => navigate('/investigations')}
        />
        <Metric
          label="Awaiting approval"
          value={pending.length.toString().padStart(2, '0')}
          detail="Separate human decision required"
          icon={FileCheck2}
          onClick={() => navigate('/changes?view=Approvals')}
        />
      </div>
      {attention && (
        <div className="attention-strip">
          <div className="attention-symbol">
            <TriangleAlert size={20} />
          </div>
          <div className="attention-copy">
            <div>
              <Badge tone="critical" dot={false}>
                {attention.severity === 'Critical' ? 'P1' : 'ACTIVE'}
              </Badge>
              <strong>{attention.title}</strong>
            </div>
            <p>
              <span className="mono">{attention.id}</span>
              <span>/</span>
              {attention.service}
              <span>/</span>
              {attention.status}
            </p>
          </div>
          <div className="attention-sla">
            <Clock3 size={15} />
            <span>{sla(attention, data.snapshotAt).label}</span>
          </div>
          <Button
            onClick={() => {
              selectIncident(attention.id)
              navigate('/war-room')
            }}
          >
            <Network size={16} />
            Open War Room
            <ArrowUpRight size={15} />
          </Button>
        </div>
      )}
      <div className="overview-analysis-grid">
        <section className="workspace-section trend-section">
          <SectionHeader
            title="Incident activity"
            caption="7 daily snapshot buckets / all environments"
            actions={
              <div className="chart-key">
                <span>
                  <i className="key-dot red" />
                  Critical
                </span>
                <span>
                  <i className="key-dot dark" />
                  High
                </span>
                <span>
                  <i className="key-dot grey" />
                  Medium & low
                </span>
              </div>
            }
          />
          <div
            className="chart-area"
            role="img"
            aria-label="Synthetic incident trend over seven days"
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={data.trends}
                barSize={27}
                margin={{ top: 12, right: 12, left: -28, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 4"
                  vertical={false}
                  stroke="#ECEDEF"
                />
                <XAxis
                  dataKey="date"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: '#707378', fontSize: 11 }}
                  dy={8}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: '#707378', fontSize: 11 }}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ fill: '#F5F5F5' }}
                  contentStyle={{
                    borderRadius: 6,
                    border: '1px solid #E5E5E5',
                    fontSize: 12,
                  }}
                />
                <Bar
                  isAnimationActive={false}
                  dataKey="other"
                  name="Medium & low"
                  stackId="incidents"
                  fill="#E5E5E5"
                />
                <Bar
                  isAnimationActive={false}
                  dataKey="high"
                  name="High"
                  stackId="incidents"
                  fill="#8D9095"
                />
                <Bar
                  isAnimationActive={false}
                  dataKey="critical"
                  name="Critical"
                  stackId="incidents"
                  fill="#F5362A"
                  radius={[3, 3, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-summary">
            <span>
              <span className="mono">
                {data.trends.reduce(
                  (total, point) => total + point.resolved,
                  0
                )}
              </span>{' '}
              resolved in historical fixture
            </span>
            <Link to="/reports">
              View analytics
              <ArrowUpRight size={13} />
            </Link>
          </div>
        </section>
        <section className="workspace-section service-health-section">
          <SectionHeader
            title="Service health"
            caption={`${services.length} services / snapshot telemetry`}
            actions={
              <Link
                className="icon-link"
                to="/war-room"
                aria-label="Open service topology"
              >
                <ArrowUpRight size={18} />
              </Link>
            }
          />
          <div className="health-visual">
            <div
              className="health-donut"
              role="img"
              aria-label={health
                .map((item) => `${item.value} ${item.name}`)
                .join(', ')}
            >
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    isAnimationActive={false}
                    data={health}
                    dataKey="value"
                    innerRadius={49}
                    outerRadius={64}
                    startAngle={90}
                    endAngle={-270}
                    paddingAngle={4}
                    stroke="none"
                  >
                    {health.map((item, index) => (
                      <Cell
                        key={item.name}
                        fill={['#45494E', '#D6D7D9', '#F5362A'][index]}
                      />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="donut-center">
                <strong>{services.length}</strong>
                <span>services</span>
              </div>
            </div>
            <div className="health-legend">
              {health.map((item, index) => (
                <div key={item.name}>
                  <i className={`key-dot ${['dark', 'grey', 'red'][index]}`} />
                  <span>{item.name}</span>
                  <strong>{item.value.toString().padStart(2, '0')}</strong>
                </div>
              ))}
            </div>
          </div>
          <div className="health-service-list">
            {services
              .filter((record) => record.health !== 'Healthy')
              .slice(0, 3)
              .map((record) => (
                <button
                  key={record.id}
                  onClick={() => navigate(`/war-room?service=${record.id}`)}
                >
                  <span
                    className={`health-state ${record.health.toLowerCase()}`}
                  />
                  <span>{record.name}</span>
                  <span className="mono">
                    {record.latency.toLocaleString()} ms
                  </span>
                  <ChevronRight size={13} />
                </button>
              ))}
            {!services.length && (
              <p className="muted">
                No service topology snapshot for this environment.
              </p>
            )}
          </div>
        </section>
      </div>
      <div className="overview-operations-grid">
        <section className="workspace-section incident-queue">
          <SectionHeader
            title="Active incident queue"
            caption={`${open.length} open / prioritized by severity`}
            actions={
              <Link className="text-link" to="/incidents">
                All incidents
                <ArrowRight size={14} />
              </Link>
            }
          />
          <DataTable
            data={active}
            columns={columns}
            onRowClick={openIncident}
            searchable={false}
            pageSize={6}
            emptyTitle="No open incidents"
            emptyDescription="There are no open incidents in the selected scope."
          />
        </section>
        <section className="workspace-section agent-pulse">
          <SectionHeader
            title="Agent activity"
            caption="Bounded synthetic workflow"
            actions={
              <Link
                className="icon-link"
                to="/agents"
                aria-label="Open agent orchestration"
              >
                <ArrowUpRight size={17} />
              </Link>
            }
          />
          <div className="agent-progress-heading">
            <span>
              {completedTasks} of {tasks.length} tasks completed
            </span>
            <strong>
              {tasks.length
                ? Math.round((completedTasks / tasks.length) * 100)
                : 0}
              %
            </strong>
          </div>
          <div className="progress-track">
            <span
              style={{
                width: `${tasks.length ? (completedTasks / tasks.length) * 100 : 0}%`,
              }}
            />
          </div>
          <div className="agent-pulse-list">
            {tasks.slice(0, 5).map((agent) => (
              <button
                key={agent.id}
                onClick={() => {
                  selectIncident(agent.incidentId)
                  navigate(`/agents?task=${agent.id}`)
                }}
              >
                <span className="agent-icon">
                  <Bot size={17} />
                </span>
                <span>
                  <strong>{agent.name}</strong>
                  <small>{agent.status}</small>
                </span>
                <i
                  className={`agent-status-dot ${agent.status === 'Running' ? 'running' : ''}`}
                />
              </button>
            ))}
            {!tasks.length && (
              <EmptyState
                title="No tasks in scope"
                description="No agent workflow is linked to these incident records."
              />
            )}
          </div>
          <div className="agent-pulse-footer">
            <ShieldCheck size={14} />
            Production writes require human approval
          </div>
        </section>
      </div>
      <div className="resolution-indicators">
        <div>
          <span>
            <CheckCheck size={15} />
            Test results
          </span>
          <strong>
            {passed}
            <small> passed / {failed} failed</small>
          </strong>
        </div>
        <div>
          <span>
            <GitPullRequest size={15} />
            Pending changes
          </span>
          <strong>
            {pending.length}
            <small> awaiting approval</small>
          </strong>
        </div>
        <div>
          <span>
            <Timer size={15} />
            MTTA
          </span>
          <strong>
            {incidents.some((incident) => incident.id === 'INC-1042')
              ? '2m'
              : '--'}
            <small>
              {' '}
              {incidents.some((incident) => incident.id === 'INC-1042')
                ? '1 measured acknowledgement'
                : 'not measured'}
            </small>
          </strong>
        </div>
        <div>
          <span>
            <Clock3 size={15} />
            MTTR
          </span>
          <strong>
            --<small>no complete measured cohort</small>
          </strong>
        </div>
        <div>
          <span>
            <Zap size={15} />
            AI-assisted resolution
          </span>
          <strong>
            --<small>not measured in demo</small>
          </strong>
        </div>
      </div>
      <div className="overview-bottom-grid">
        <section className="workspace-section">
          <SectionHeader
            title="Approval queue"
            caption="Human review"
            actions={
              <Link
                to="/changes?view=Approvals"
                className="icon-link"
                aria-label="View approvals"
              >
                <ArrowUpRight size={16} />
              </Link>
            }
          />
          {pending.length ? (
            pending.map((approval) => (
              <button
                className="approval-preview"
                key={approval.id}
                onClick={() => {
                  selectIncident(approval.incidentId)
                  navigate('/changes?view=Approvals')
                }}
              >
                <span className="outline-symbol">
                  <FileCheck2 size={19} />
                </span>
                <span>
                  <strong>{approval.title}</strong>
                  <small>
                    {approval.changeId} / {approval.requestedBy}
                  </small>
                  <Badge>Pending</Badge>
                </span>
                <ChevronRight size={15} />
              </button>
            ))
          ) : (
            <EmptyState
              title="No pending decisions"
              description="The current scope has no approval requests."
            />
          )}
          <div className="mini-section-title">Recent deployments</div>
          {data.deployments
            .filter((deployment) => deployment.environment === environment)
            .slice(0, 2)
            .map((deployment) => (
              <button
                key={deployment.id}
                className="deployment-preview"
                onClick={() => navigate('/changes')}
              >
                <GitPullRequest size={15} />
                <div>
                  <strong>{deployment.service}</strong>
                  <small>
                    {deployment.version} / {dateTime(deployment.timestamp)}
                  </small>
                </div>
                <Badge dot={false}>{deployment.status}</Badge>
              </button>
            ))}
        </section>
        <section className="workspace-section">
          <SectionHeader
            title="Risk watch"
            caption="SLA & security / synthetic findings"
            actions={
              <Link
                to="/security"
                className="icon-link"
                aria-label="View security findings"
              >
                <ArrowUpRight size={16} />
              </Link>
            }
          />
          {slaRisk.map((incident) => (
            <button
              className="risk-preview"
              key={incident.id}
              onClick={() => openIncident(incident)}
            >
              <Clock3 size={17} />
              <div>
                <strong>{incident.service}</strong>
                <small>
                  {incident.id} / {sla(incident, data.snapshotAt).label}
                </small>
              </div>
              <Badge tone="critical">SLA risk</Badge>
            </button>
          ))}
          {data.security
            .filter((finding) => finding.status !== 'Resolved')
            .slice(0, 2)
            .map((finding) => (
              <button
                className="risk-preview"
                key={finding.id}
                onClick={() => navigate(`/security?finding=${finding.id}`)}
              >
                <ShieldCheck size={17} />
                <div>
                  <strong>{finding.title}</strong>
                  <small>{finding.service}</small>
                </div>
                <Badge>{finding.severity}</Badge>
              </button>
            ))}
        </section>
        <section className="workspace-section">
          <SectionHeader
            title="Recent audit activity"
            caption="Persisted local audit records"
            actions={
              <Link
                to="/audit"
                className="icon-link"
                aria-label="View audit trail"
              >
                <ArrowUpRight size={16} />
              </Link>
            }
          />
          <div className="audit-preview-list">
            {data.audit.slice(0, 4).map((event) => (
              <Link key={event.id} to={`/audit?event=${event.id}`}>
                <i />
                <div>
                  <strong>{event.action}</strong>
                  <small>
                    {event.actor} / {event.resource}
                  </small>
                </div>
                <time>{time(event.timestamp).slice(0, 5)}</time>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

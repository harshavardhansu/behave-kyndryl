import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ColumnDef } from '@tanstack/react-table'
import {
  ArrowUpRight,
  BarChart3,
  Calculator,
  CheckCheck,
  Clock3,
  Download,
  FileSearch,
  Timer,
  TriangleAlert,
} from 'lucide-react'
import { useWorkspace } from '../context'
import { closedStatuses, dateTime, severities, sla } from '../lib/format'
import {
  Badge,
  Button,
  DataTable,
  Metric,
  Notice,
  PageHeader,
  SectionHeader,
  Select,
  Tabs,
} from '../components/ui'

interface MetricDefinition {
  metric: string
  value: string
  denominator: string
  definition: string
  source: string
}

export function Reports() {
  const { data, environment, exportReport } = useWorkspace()
  const [referenceTime] = useState(Date.now)
  const [tab, setTab] = useState('Operational analytics')
  const [service, setService] = useState('All services')
  const [severity, setSeverity] = useState('All severities')
  const [owner, setOwner] = useState('All owners')
  const [range, setRange] = useState('7 days')
  const [estimate, setEstimate] = useState({
    baselineMinutes: 45,
    assistedMinutes: 30,
    incidentsPerMonth: 100,
    hourlyCost: 60,
  })
  const cutoff =
    Math.max(referenceTime, new Date(data.snapshotAt).getTime()) -
    (range === '24 hours' ? 1 : range === '7 days' ? 7 : 30) * 86_400_000
  const incidents = data.incidents.filter(
    (incident) =>
      incident.environment === environment &&
      (service === 'All services' || incident.service === service) &&
      (severity === 'All severities' || incident.severity === severity) &&
      (owner === 'All owners' || incident.owner === owner) &&
      new Date(incident.detectedAt).getTime() >= cutoff
  )
  const ids = new Set(incidents.map((incident) => incident.id))
  const open = incidents.filter(
    (incident) => !closedStatuses.includes(incident.status)
  )
  const tests = data.tests.filter((test) => ids.has(test.incidentId))
  const totalTests = tests.reduce(
    (total, test) => total + test.passed + test.failed,
    0
  )
  const failedTests = tests.reduce((total, test) => total + test.failed, 0)
  const tasks = data.agents.filter((agent) => ids.has(agent.incidentId))
  const terminalTasks = tasks.filter((task) =>
    ['Completed', 'Failed', 'Cancelled'].includes(task.status)
  )
  const completedTasks = terminalTasks.filter(
    (task) => task.status === 'Completed'
  ).length
  const withEvidence = incidents.filter((incident) =>
    data.evidence.some((record) => record.incidentId === incident.id)
  ).length
  const acknowledgements = incidents.flatMap((incident) => {
    const acknowledgement = data.audit.find(
      (event) =>
        event.correlationId === incident.id &&
        event.action === 'Incident acknowledged'
    )
    return acknowledgement
      ? [
          (new Date(acknowledgement.timestamp).getTime() -
            new Date(incident.detectedAt).getTime()) /
            60_000,
        ]
      : []
  })
  const resolutions = incidents.flatMap((incident) => {
    const closure = data.audit.find(
      (event) =>
        event.correlationId === incident.id && event.action === 'verify'
    )
    return closure
      ? [
          (new Date(closure.timestamp).getTime() -
            new Date(incident.detectedAt).getTime()) /
            60_000,
        ]
      : []
  })
  const decisions = data.approvals.filter(
    (approval) => ids.has(approval.incidentId) && approval.decidedAt
  )
  const average = (values: number[]) =>
    values.length
      ? `${(values.reduce((total, value) => total + value, 0) / values.length).toFixed(1)}m`
      : '--'
  const ratio = (numerator: number, denominator: number) =>
    denominator ? `${((numerator / denominator) * 100).toFixed(1)}%` : '--'
  const distribution = severities.map((name) => ({
    name,
    count: incidents.filter((incident) => incident.severity === name).length,
  }))
  const definitions: MetricDefinition[] = [
    {
      metric: 'Mean time to acknowledge',
      value: average(acknowledgements),
      denominator: `${acknowledgements.length} acknowledged incidents`,
      definition:
        'Average detection-to-human-acknowledgement duration where both timestamps exist.',
      source: 'Incident & audit records',
    },
    {
      metric: 'Mean time to detect',
      value: '--',
      denominator: 'No independently recorded failure-onset timestamps',
      definition:
        'Failure onset to detection; unavailable without a verified onset time.',
      source: 'Not measurable in this fixture',
    },
    {
      metric: 'Mean time to resolve',
      value: average(resolutions),
      denominator: `${resolutions.length} verified recoveries`,
      definition: 'Average incident detection-to-recorded-recovery duration.',
      source: 'Recovery audit records',
    },
    {
      metric: 'Incident backlog',
      value: String(open.length),
      denominator: `${incidents.length} incident records in scope`,
      definition: 'Incidents not in Resolved or Closed state.',
      source: 'Persisted incident states',
    },
    {
      metric: 'SLA risk',
      value: String(
        open.filter((incident) => sla(incident, data.snapshotAt).risk).length
      ),
      denominator: `${open.length} open records`,
      definition:
        'Open incidents with at most 30 minutes remaining in their fixture SLA window.',
      source: 'Snapshot timestamps & incident SLA',
    },
    {
      metric: 'SLA compliance',
      value: '--',
      denominator: 'No complete contractual SLA cohort',
      definition:
        'Eligible incidents meeting their contractual SLA; not inferred from the current backlog.',
      source: 'Not measured',
    },
    {
      metric: 'Test failure rate',
      value: ratio(failedTests, totalTests),
      denominator: `${failedTests} failed / ${totalTests} non-skipped checks`,
      definition:
        'Failed checks divided by passed plus failed checks across selected recorded runs.',
      source: 'Synthetic or manually recorded test runs',
    },
    {
      metric: 'Agent task success rate',
      value: ratio(completedTasks, terminalTasks.length),
      denominator: `${completedTasks} completed / ${terminalTasks.length} terminal tasks`,
      definition:
        'Completed tasks divided by completed, failed and cancelled tasks. No model evaluation is implied.',
      source: 'Synthetic workflow state',
    },
    {
      metric: 'Human approval wait time',
      value: average(
        decisions.map(
          (approval) =>
            (new Date(approval.decidedAt!).getTime() -
              new Date(approval.requestedAt).getTime()) /
            60_000
        )
      ),
      denominator: `${decisions.length} decided requests`,
      definition: 'Average request-to-decision interval for decided approvals.',
      source: 'Human approval records',
    },
    {
      metric: 'Evidence coverage',
      value: ratio(withEvidence, incidents.length),
      denominator: `${withEvidence} linked / ${incidents.length} incidents`,
      definition:
        'Share of incident records with at least one linked evidence record; not evidence completeness.',
      source: 'Incident/evidence references',
    },
    {
      metric: 'Reopen rate',
      value: ratio(
        incidents.filter((incident) => incident.status === 'Reopened').length,
        incidents.length
      ),
      denominator: `${incidents.length} incident records`,
      definition:
        'Current reopened incidents divided by records in scope; not a historical recurrence measure.',
      source: 'Current incident states',
    },
    {
      metric: 'Incident recurrence',
      value: '--',
      denominator: 'No validated recurrence groups',
      definition: 'Repeated incidents with a validated common failure mode.',
      source: 'Not measured',
    },
    {
      metric: 'Change failure rate',
      value: '--',
      denominator: 'No real deployment outcome cohort',
      definition:
        'Changes causing a validated incident or rollback divided by eligible deployments.',
      source: 'No connected deployment provider',
    },
    {
      metric: 'Rollback frequency',
      value: String(
        data.deployments.filter(
          (deployment) =>
            deployment.status === 'Simulated rollback' &&
            deployment.environment === environment
        ).length
      ),
      denominator: 'Recorded demo rollback events in environment',
      definition:
        'Count of explicit synthetic rollback records; not a production frequency.',
      source: 'Synthetic deployment records',
    },
    {
      metric: 'Investigation duration',
      value: '--',
      denominator: 'No completed real investigation cohort',
      definition:
        'Duration from authorized investigation start to human-reviewed assessment.',
      source: 'Not measured',
    },
  ]
  const metricColumns: ColumnDef<MetricDefinition>[] = [
    {
      accessorKey: 'metric',
      header: 'Metric',
      cell: ({ getValue }) => (
        <strong className="small-copy">{String(getValue())}</strong>
      ),
    },
    {
      accessorKey: 'value',
      header: 'Value',
      cell: ({ getValue }) => (
        <span className="mono">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'denominator',
      header: 'Cohort / denominator',
      cell: ({ getValue }) => (
        <span className="metric-definition-copy">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'definition',
      header: 'Definition',
      cell: ({ getValue }) => (
        <span className="metric-definition-copy">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'source',
      header: 'Source',
      cell: ({ getValue }) => (
        <span className="metric-definition-copy">{String(getValue())}</span>
      ),
    },
  ]
  const savedHours =
    ((estimate.baselineMinutes - estimate.assistedMinutes) *
      estimate.incidentsPerMonth) /
    60
  return (
    <div className="page-enter">
      <PageHeader
        title="Reports & analytics"
        description="Explicit definitions / Traceable denominators / Measured vs. estimated"
        actions={
          <Button onClick={() => void exportReport('json')}>
            <Download size={15} />
            Export environment records
          </Button>
        }
      />
      <div className="report-filters">
        <Badge tone="outline">{environment}</Badge>
        <Select
          label="Report time range"
          value={range}
          onChange={(event) => setRange(event.target.value)}
        >
          {['24 hours', '7 days', '30 days'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </Select>
        <Select
          label="Report service"
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
        <Select
          label="Report severity"
          value={severity}
          onChange={(event) => setSeverity(event.target.value)}
        >
          <option>All severities</option>
          {severities.map((value) => (
            <option key={value}>{value}</option>
          ))}
        </Select>
        <Select
          label="Report owner"
          value={owner}
          onChange={(event) => setOwner(event.target.value)}
        >
          <option>All owners</option>
          {[...new Set(data.incidents.map((record) => record.owner))].map(
            (value) => (
              <option key={value}>{value}</option>
            )
          )}
        </Select>
      </div>
      <Tabs
        items={[
          'Operational analytics',
          'Metric definitions',
          'Effort estimator',
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'Operational analytics' && (
        <>
          <div className="metrics-grid four">
            <Metric
              label="Mean time to acknowledge"
              value={average(acknowledgements)}
              detail={`${acknowledgements.length} eligible records / demo data`}
              icon={Timer}
            />
            <Metric
              label="Mean time to resolve"
              value={average(resolutions)}
              detail={`${resolutions.length} verified recovery records`}
              icon={Clock3}
            />
            <Metric
              label="Evidence coverage"
              value={ratio(withEvidence, incidents.length)}
              detail={`${withEvidence} of ${incidents.length} incidents have evidence`}
              icon={FileSearch}
            />
            <Metric
              label="Test pass rate"
              value={ratio(totalTests - failedTests, totalTests)}
              detail={`${totalTests} recorded non-skipped checks`}
              icon={CheckCheck}
            />
          </div>
          <div className="reports-chart-grid">
            <section className="workspace-section">
              <SectionHeader
                title="Severity distribution"
                caption={`${incidents.length} incidents / selected filters`}
              />
              <div
                className="report-chart"
                role="img"
                aria-label="Incident severity distribution"
              >
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={distribution}
                    barSize={42}
                    margin={{ left: -20, right: 15, top: 10 }}
                  >
                    <CartesianGrid
                      vertical={false}
                      stroke="#ECEEEF"
                      strokeDasharray="3 4"
                    />
                    <XAxis
                      dataKey="name"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 11, fill: '#7A838C' }}
                    />
                    <YAxis
                      allowDecimals={false}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: '#7A838C' }}
                    />
                    <Tooltip cursor={{ fill: '#F5F5F5' }} />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                      {distribution.map((record, index) => (
                        <Cell
                          key={record.name}
                          fill={
                            ['#F5362A', '#666D74', '#B4B9BE', '#E0E2E4'][index]
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>
            <section className="workspace-section">
              <SectionHeader
                title="Resolution trend fixture"
                caption="Fixed historical fixture / 7 days / all environments"
              />
              <div
                className="report-chart"
                role="img"
                aria-label="Historical synthetic resolution trend"
              >
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={data.trends}
                    margin={{ left: -20, right: 15, top: 10 }}
                  >
                    <CartesianGrid
                      vertical={false}
                      stroke="#ECEEEF"
                      strokeDasharray="3 4"
                    />
                    <XAxis
                      dataKey="date"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: '#7A838C' }}
                    />
                    <YAxis
                      allowDecimals={false}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: '#7A838C' }}
                    />
                    <Tooltip />
                    <Line
                      isAnimationActive={false}
                      type="linear"
                      dataKey="resolved"
                      stroke="#F5362A"
                      strokeWidth={2.2}
                      dot={{ r: 3, fill: '#FFFFFF', strokeWidth: 2 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>
          </div>
          <Notice title="Demo analytics, not production results">
            Values are calculated from synthetic and user-entered records.
            Missing measurements remain unreported. The historical trend fixture
            is independent of the incident filters.
          </Notice>
          <div className="report-links">
            <Link to="/incidents">
              <TriangleAlert size={18} />
              <div>
                <strong>Incident operations</strong>
                <small>Inspect the source cohort</small>
              </div>
              <ArrowUpRight size={16} />
            </Link>
            <Link to="/audit">
              <BarChart3 size={18} />
              <div>
                <strong>Audit & decision history</strong>
                <small>Review the underlying actions</small>
              </div>
              <ArrowUpRight size={16} />
            </Link>
          </div>
        </>
      )}
      {tab === 'Metric definitions' && (
        <>
          <SectionHeader
            title="Operational metric register"
            caption={`${environment} / last ${range} / ${incidents.length} incident records`}
          />
          <DataTable
            data={definitions}
            columns={metricColumns}
            pageSize={12}
            searchPlaceholder="Search definitions or sources"
          />
          <p className="source-note">
            Snapshot captured {dateTime(data.snapshotAt)}. A zero denominator is
            shown as unavailable, not a 0% or 100% success claim.
          </p>
        </>
      )}
      {tab === 'Effort estimator' && (
        <>
          <Notice title="Scenario estimates only">
            These editable assumptions are illustrative, not measured savings.
            No AI effectiveness, handoff reduction, recurrence reduction,
            delivery improvement or cost guarantee is implied.
          </Notice>
          <div className="estimator-layout">
            <section>
              <SectionHeader
                title="Scenario assumptions"
                caption="User-adjustable inputs / not telemetry"
              />
              <div className="form-grid">
                {(
                  [
                    {
                      field: 'baselineMinutes',
                      label: 'Baseline handling time (minutes)',
                    },
                    {
                      field: 'assistedMinutes',
                      label: 'Assisted handling time (minutes)',
                    },
                    {
                      field: 'incidentsPerMonth',
                      label: 'Incidents per month',
                    },
                    { field: 'hourlyCost', label: 'Loaded hourly cost (USD)' },
                  ] as const
                ).map((input) => (
                  <label className="field-label" key={input.field}>
                    {input.label}
                    <input
                      type="number"
                      min="0"
                      max="100000"
                      value={estimate[input.field]}
                      onChange={(event) =>
                        setEstimate({
                          ...estimate,
                          [input.field]: Math.max(
                            0,
                            Math.min(100000, Number(event.target.value))
                          ),
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              <div className="estimator-formula">
                <Calculator size={19} />
                <span>
                  (Baseline minutes - assisted minutes) x monthly volume / 60
                </span>
              </div>
            </section>
            <section className="estimator-results">
              <Badge tone="outline">Scenario estimate</Badge>
              <div>
                <span>Estimated monthly time difference</span>
                <strong>
                  {savedHours.toFixed(1)}
                  <small> hours</small>
                </strong>
              </div>
              <div>
                <span>Estimated monthly cost difference</span>
                <strong>
                  {(savedHours * estimate.hourlyCost).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD',
                    maximumFractionDigits: 0,
                  })}
                </strong>
              </div>
              <p>
                Negative values indicate increased time or cost. Model,
                infrastructure, review and implementation costs are not
                included.
              </p>
            </section>
          </div>
        </>
      )}
    </div>
  )
}

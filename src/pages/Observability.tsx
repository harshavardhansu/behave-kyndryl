import { useDeferredValue, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Braces,
  Clock3,
  Database,
  FileText,
  GitBranch,
  Upload,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import type { LogRecord } from '../types'
import { dateTime, number, time } from '../lib/format'
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  KeyValue,
  Notice,
  PageHeader,
  SectionHeader,
  Select,
  Tabs,
} from '../components/ui'
import { EvidenceLinks, IncidentSelector } from '../components/incident'

interface ErrorGroup {
  fingerprint: string
  service: string
  level: string
  count: number
  first: string
  last: string
  message: string
}

export function Observability() {
  const { data, environment, can, setEvidenceFor } = useWorkspace()
  const incident = useIncident()
  const [params] = useSearchParams()
  const [tab, setTab] = useState('Log explorer')
  const [service, setService] = useState(
    params.get('service') || 'All services'
  )
  const [level, setLevel] = useState('All levels')
  const [range, setRange] = useState('Last hour')
  const [field, setField] = useState('traceId')
  const [fieldValue, setFieldValue] = useState('')
  const deferredFieldValue = useDeferredValue(fieldValue)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [traceId, setTraceId] = useState('trace-a83f12')
  const anchor = Math.max(
    new Date(data.snapshotAt).getTime(),
    ...data.logs.map((log) => new Date(log.timestamp).getTime())
  )
  const cutoff =
    anchor -
    (range === 'Last 15 minutes' ? 15 : range === 'Last hour' ? 60 : 1440) *
      60_000
  const logs = data.logs
    .filter(
      (log) =>
        log.environment === environment &&
        (service === 'All services' || log.service === service) &&
        (level === 'All levels' || log.level === level) &&
        new Date(log.timestamp).getTime() >= cutoff &&
        (!deferredFieldValue ||
          String(
            field === 'traceId'
              ? log.traceId
              : field === 'source'
                ? log.source
                : (log.attributes[field] ?? '')
          )
            .toLowerCase()
            .includes(deferredFieldValue.toLowerCase()))
    )
    .sort((first, second) => second.timestamp.localeCompare(first.timestamp))
  const selected = data.logs.find((log) => log.id === selectedId)
  const grouped = new Map<string, ErrorGroup>()
  logs
    .filter((log) => ['ERROR', 'WARN'].includes(log.level))
    .forEach((log) => {
      const fingerprint = String(
        log.attributes.fingerprint ??
          `${log.service}:${log.level}:${log.message.slice(0, 60)}`
      )
      const current = grouped.get(fingerprint)
      grouped.set(fingerprint, {
        fingerprint,
        service: log.service,
        level: log.level,
        count: (current?.count ?? 0) + 1,
        first:
          current && current.first < log.timestamp
            ? current.first
            : log.timestamp,
        last:
          current && current.last > log.timestamp
            ? current.last
            : log.timestamp,
        message: log.message,
      })
    })
  const groups = [...grouped.values()].sort(
    (first, second) => second.count - first.count
  )
  const traces = [...new Set(logs.map((log) => log.traceId).filter(Boolean))]
  const columns: ColumnDef<LogRecord>[] = [
    {
      accessorKey: 'timestamp',
      header: 'Timestamp',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{time(String(getValue()))}</span>
      ),
    },
    {
      accessorKey: 'level',
      header: 'Level',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    {
      accessorKey: 'service',
      header: 'Service',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'message',
      header: 'Message',
      cell: ({ getValue }) => (
        <span className="log-message">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'traceId',
      header: 'Trace context',
      cell: ({ getValue }) => (
        <span className="mono trace-cell">{String(getValue()) || '--'}</span>
      ),
    },
  ]
  const groupColumns: ColumnDef<ErrorGroup>[] = [
    {
      accessorKey: 'fingerprint',
      header: 'Error fingerprint',
      cell: ({ row }) => (
        <div className="incident-cell">
          <strong className="mono">{row.original.fingerprint}</strong>
          <small>{row.original.message.slice(0, 90)}</small>
        </div>
      ),
    },
    {
      accessorKey: 'level',
      header: 'Level',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    { accessorKey: 'count', header: 'Occurrences' },
    {
      accessorKey: 'first',
      header: 'First observed',
      cell: ({ getValue }) => time(String(getValue())),
    },
    {
      accessorKey: 'last',
      header: 'Last observed',
      cell: ({ getValue }) => time(String(getValue())),
    },
  ]
  return (
    <div className="page-enter">
      <PageHeader
        title="Observability & logs"
        description="Searchable evidence / Original timestamps / Explicit correlation"
        actions={
          <>
            <Link className="button button-secondary" to="/administration">
              <Database size={15} />
              Data sources
              <ArrowUpRight size={13} />
            </Link>
            <Button
              variant="primary"
              disabled={!incident || !can('evidence:add', incident.environment)}
              onClick={() => incident && setEvidenceFor(incident.id)}
            >
              <Upload size={18} />
              Import evidence
            </Button>
          </>
        }
      />
      <div className="module-context-bar">
        <IncidentSelector />
        <Badge tone="outline">
          {environment} / Snapshot & imported records
        </Badge>
      </div>
      <div className="log-filter-band">
        <Select
          label="Log service filter"
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
          label="Log severity filter"
          value={level}
          onChange={(event) => setLevel(event.target.value)}
        >
          {['All levels', 'ERROR', 'WARN', 'INFO', 'DEBUG'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </Select>
        <Select
          label="Log time range"
          value={range}
          onChange={(event) => setRange(event.target.value)}
        >
          {['Last 15 minutes', 'Last hour', 'Last 24 hours'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </Select>
        <div className="structured-filter">
          <Select
            label="Structured log field"
            value={field}
            onChange={(event) => setField(event.target.value)}
          >
            <option value="traceId">Trace ID</option>
            <option value="requestId">Request ID</option>
            <option value="deployment">Deployment</option>
            <option value="fingerprint">Fingerprint</option>
            <option value="source">Source</option>
          </Select>
          <input
            aria-label="Structured field value"
            placeholder="Filter by field value..."
            value={fieldValue}
            onChange={(event) => setFieldValue(event.target.value)}
          />
        </div>
      </div>
      <div className="log-summary">
        <span>
          <FileText size={14} />
          <strong>{logs.length}</strong> records
        </span>
        <span>
          <Activity size={14} />
          <strong>
            {logs.filter((log) => log.level === 'ERROR').length}
          </strong>{' '}
          errors
        </span>
        <span>
          <GitBranch size={14} />
          <strong>{traces.length}</strong> trace contexts
        </span>
        <span className="log-range-note">
          <Clock3 size={12} />
          Relative to latest available record
        </span>
      </div>
      <Tabs
        items={[
          'Log explorer',
          'Error groups',
          'Trace explorer',
          'Service metrics',
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'Log explorer' && (
        <DataTable
          data={logs}
          columns={columns}
          onRowClick={(log) => setSelectedId(log.id)}
          searchPlaceholder="Search log messages, services or trace IDs"
          pageSize={12}
          emptyTitle="No matching log records"
          emptyDescription="Adjust the service, level, time range or structured field filter. No live telemetry source is connected."
        />
      )}
      {tab === 'Error groups' && (
        <>
          <Notice title="Grouping is evidence, not causation">
            Records share an explicit source fingerprint or a service, severity
            and message prefix in the selected window. An error near a
            deployment is not proof that the deployment caused it.
          </Notice>
          <div className="section-spacer" />
          <DataTable
            data={groups}
            columns={groupColumns}
            onRowClick={(group) => {
              setService(group.service)
              setLevel(group.level)
              setField('fingerprint')
              setFieldValue(group.fingerprint)
              setTab('Log explorer')
            }}
            searchPlaceholder="Search error fingerprints"
          />
        </>
      )}
      {tab === 'Trace explorer' && (
        <>
          <SectionHeader
            title="Distributed trace evidence"
            caption="Pre-recorded span excerpt / no live tracing connection"
            actions={
              <Select
                label="Trace selection"
                value={traceId}
                onChange={(event) => setTraceId(event.target.value)}
              >
                {[...new Set([traceId, ...traces])].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </Select>
            }
          />
          {traceId === 'trace-a83f12' && traces.includes(traceId) ? (
            <>
              <div className="trace-heading">
                <div>
                  <span className="eyebrow">POST /api/v1/checkout</span>
                  <h2>Connection acquisition dominates the sampled request</h2>
                </div>
                <Badge tone="critical">2,014 ms / Error</Badge>
              </div>
              <div className="trace-waterfall">
                <div className="trace-scale">
                  <span>0 ms</span>
                  <span>500 ms</span>
                  <span>1,000 ms</span>
                  <span>1,500 ms</span>
                  <span>2,014 ms</span>
                </div>
                {[
                  {
                    name: 'checkout-svc / POST /checkout',
                    start: 0,
                    duration: 2014,
                    critical: true,
                  },
                  {
                    name: 'payment-svc / authorize',
                    start: 0,
                    duration: 186,
                    critical: false,
                  },
                  {
                    name: 'rds-proxy / acquire_connection',
                    start: 186,
                    duration: 1811,
                    critical: true,
                  },
                ].map((span) => (
                  <div className="trace-span" key={span.name}>
                    <span className="mono">{span.name}</span>
                    <div>
                      <i
                        className={span.critical ? 'critical' : ''}
                        style={{
                          marginLeft: `${(span.start / 2014) * 100}%`,
                          width: `${(span.duration / 2014) * 100}%`,
                        }}
                      />
                      <strong>{span.duration} ms</strong>
                    </div>
                  </div>
                ))}
              </div>
              <EvidenceLinks ids={['EVD-303', 'EVD-305']} />
              <Notice title="Competing explanation remains visible">
                The payment span is within its fixture baseline. The database
                acquisition delay supports a pool-saturation hypothesis, but a
                controlled comparison is still required.
              </Notice>
            </>
          ) : (
            <EmptyState
              title="No span export available for this trace"
              description="A correlation ID exists in logs, but it does not supply a complete distributed trace."
            />
          )}
          <div className="section-spacer" />
          <DataTable
            data={logs.filter((log) => log.traceId === traceId)}
            columns={columns}
            onRowClick={(log) => setSelectedId(log.id)}
            searchPlaceholder="Search records in this trace"
          />
        </>
      )}
      {tab === 'Service metrics' && (
        <>
          <SectionHeader
            title="Service telemetry snapshot"
            caption={`${dateTime(data.snapshotAt)} / no historical metric stream`}
          />
          <div className="service-metric-grid">
            {data.services
              .filter(
                (record) =>
                  record.environment === environment &&
                  (service === 'All services' || record.id === service)
              )
              .map((record) => (
                <Link key={record.id} to={`/war-room?service=${record.id}`}>
                  <div>
                    <span
                      className={`node-health-dot ${record.health.toLowerCase()}`}
                    />
                    <strong>{record.name}</strong>
                    <ArrowUpRight size={14} />
                  </div>
                  <dl>
                    <div>
                      <dt>p95 latency</dt>
                      <dd>
                        {number(record.latency)}
                        <small> ms</small>
                      </dd>
                    </div>
                    <div>
                      <dt>Error rate</dt>
                      <dd>
                        {record.errorRate}
                        <small>%</small>
                      </dd>
                    </div>
                    <div>
                      <dt>Throughput</dt>
                      <dd>
                        {number(record.rps)}
                        <small> rps</small>
                      </dd>
                    </div>
                  </dl>
                  <Badge tone="outline">{record.type}</Badge>
                </Link>
              ))}
          </div>
        </>
      )}
      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelectedId(null)}
        title="Log record"
        subtitle={selected?.id}
      >
        {selected && (
          <>
            <div className="detail-badges">
              <Badge>{selected.level}</Badge>
              <Badge tone="outline">{selected.environment}</Badge>
            </div>
            <pre className="evidence-excerpt">{selected.message}</pre>
            <dl>
              <KeyValue label="Original timestamp" mono>
                {selected.timestamp}
              </KeyValue>
              <KeyValue label="Service" mono>
                {selected.service}
              </KeyValue>
              <KeyValue label="Source reference" mono>
                {selected.source}
              </KeyValue>
              <KeyValue label="Trace ID" mono>
                {selected.traceId || 'Not supplied'}
              </KeyValue>
            </dl>
            <h3 className="detail-section-title">Structured attributes</h3>
            <pre className="evidence-excerpt">
              {JSON.stringify(selected.attributes, null, 2)}
            </pre>
            <h3 className="detail-section-title">Related evidence</h3>
            <EvidenceLinks ids={[selected.evidenceId]} />
            <Button
              onClick={() => {
                setTraceId(selected.traceId)
                setTab('Trace explorer')
                setSelectedId(null)
              }}
              disabled={!selected.traceId}
            >
              <Braces size={15} />
              Inspect trace context
              <ArrowRight size={13} />
            </Button>
            <Notice title="Provenance retained">
              Original source references and record timestamps are preserved.
              Sensitive values are redacted; imported records are never
              executed.
            </Notice>
          </>
        )}
      </Drawer>
    </div>
  )
}

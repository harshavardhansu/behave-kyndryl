import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import { ArrowRight, Download, FileClock, ShieldCheck } from 'lucide-react'
import { useWorkspace } from '../context'
import { dateTime, environments } from '../lib/format'
import type { AuditEvent } from '../types'
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  KeyValue,
  Notice,
  PageHeader,
  Select,
} from '../components/ui'
import { EvidenceLinks } from '../components/incident'

export function Audit() {
  const { data, exportReport } = useWorkspace()
  const [referenceTime] = useState(Date.now)
  const [params] = useSearchParams()
  const [selectedId, setSelectedId] = useState<string | null>(
    params.get('event')
  )
  const [actor, setActor] = useState('All actors')
  const [action, setAction] = useState('All actions')
  const [environment, setEnvironment] = useState('All environments')
  const [range, setRange] = useState('Last 24 hours')
  const cutoff =
    Math.max(referenceTime, new Date(data.snapshotAt).getTime()) -
    (range === 'Last 24 hours' ? 1 : range === 'Last 7 days' ? 7 : 365) *
      86_400_000
  const events = data.audit.filter(
    (event) =>
      (actor === 'All actors' || event.actor === actor) &&
      (action === 'All actions' || event.action === action) &&
      (environment === 'All environments' ||
        event.environment === environment) &&
      new Date(event.timestamp).getTime() >= cutoff
  )
  const selected = data.audit.find((event) => event.id === selectedId)
  const columns: ColumnDef<AuditEvent>[] = [
    {
      accessorKey: 'timestamp',
      header: 'Timestamp',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{dateTime(String(getValue()))}</span>
      ),
    },
    {
      accessorKey: 'actor',
      header: 'Identity',
      cell: ({ row }) => (
        <div className="incident-cell">
          <strong>{row.original.actor}</strong>
          <small>{row.original.role}</small>
        </div>
      ),
    },
    {
      accessorKey: 'action',
      header: 'Action',
      cell: ({ getValue }) => (
        <span className="audit-action">
          <FileClock size={13} />
          {String(getValue())}
        </span>
      ),
    },
    {
      accessorKey: 'resource',
      header: 'Resource',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{String(getValue())}</span>
      ),
    },
    { accessorKey: 'environment', header: 'Environment' },
    {
      accessorKey: 'outcome',
      header: 'Outcome',
      cell: ({ getValue }) => (
        <Badge tone="outline">{String(getValue())}</Badge>
      ),
    },
    {
      accessorKey: 'correlationId',
      header: 'Correlation',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{String(getValue())}</span>
      ),
    },
  ]
  return (
    <div className="page-enter">
      <PageHeader
        title="Audit trail"
        description="Consequential actions / Identity and state provenance / Workspace-wide records"
        actions={
          <Button onClick={() => void exportReport('json')}>
            <Download size={15} />
            Export environment report
          </Button>
        }
      />
      <div className="audit-status-band">
        <ShieldCheck size={19} />
        <div>
          <strong>Append-oriented audit history</strong>
          <p>
            The API records consequential actions and exposes no edit or delete
            endpoint for audit records.
          </p>
        </div>
        <Badge tone="outline">{data.audit.length} records</Badge>
      </div>
      <div className="audit-filters">
        <Select
          label="Audit actor filter"
          value={actor}
          onChange={(event) => setActor(event.target.value)}
        >
          <option>All actors</option>
          {[...new Set(data.audit.map((event) => event.actor))].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </Select>
        <Select
          label="Audit action filter"
          value={action}
          onChange={(event) => setAction(event.target.value)}
        >
          <option>All actions</option>
          {[...new Set(data.audit.map((event) => event.action))].map(
            (value) => (
              <option key={value}>{value}</option>
            )
          )}
        </Select>
        <Select
          label="Audit environment filter"
          value={environment}
          onChange={(event) => setEnvironment(event.target.value)}
        >
          {['All environments', ...environments, 'Workspace'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </Select>
        <Select
          label="Audit time range"
          value={range}
          onChange={(event) => setRange(event.target.value)}
        >
          {['Last 24 hours', 'Last 7 days', 'Last year'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </Select>
      </div>
      <DataTable
        data={events}
        columns={columns}
        onRowClick={(event) => setSelectedId(event.id)}
        pageSize={12}
        searchPlaceholder="Search identity, action, resource or correlation"
      />
      <div className="section-spacer" />
      <Notice title="Storage assurance boundary">
        The local SQLite database is persistent, but it is not immutable or
        tamper-resistant storage. A production deployment requires restricted
        database roles, protected backups and an external append-only audit
        sink.
      </Notice>
      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelectedId(null)}
        title={selected?.action ?? 'Audit event'}
        subtitle={selected?.id}
      >
        {selected && (
          <>
            <div className="detail-badges">
              <Badge tone="outline">{selected.outcome}</Badge>
              <Badge tone="outline">
                {selected.synthetic ? 'Demo workspace' : 'Recorded action'}
              </Badge>
            </div>
            <dl>
              <KeyValue label="User / service">{selected.actor}</KeyValue>
              <KeyValue label="Role">{selected.role}</KeyValue>
              <KeyValue label="Timestamp" mono>
                {selected.timestamp}
              </KeyValue>
              <KeyValue label="Action">{selected.action}</KeyValue>
              <KeyValue label="Resource" mono>
                {selected.resource}
              </KeyValue>
              <KeyValue label="Environment">{selected.environment}</KeyValue>
              <KeyValue label="Correlation" mono>
                {selected.correlationId}
              </KeyValue>
              <KeyValue label="Previous state">
                {selected.previous || 'No previous state'}
              </KeyValue>
              <KeyValue label="New state">
                {selected.next || 'No state change'}
              </KeyValue>
              <KeyValue label="Outcome">{selected.outcome}</KeyValue>
            </dl>
            {selected.evidence && (
              <>
                <h3 className="detail-section-title">Evidence reference</h3>
                <EvidenceLinks ids={[selected.evidence]} />
              </>
            )}
            {data.incidents.some(
              (incident) => incident.id === selected.correlationId
            ) && (
              <Link
                className="button button-secondary"
                to={`/incidents/${selected.correlationId}`}
                onClick={() => setSelectedId(null)}
              >
                Open related incident
                <ArrowRight size={14} />
              </Link>
            )}
            <Notice title="Preserved decision context">
              State changes, actor identity and environment are captured at the
              point of the action. The database is not claimed to be immutable.
            </Notice>
          </>
        )}
      </Drawer>
    </div>
  )
}

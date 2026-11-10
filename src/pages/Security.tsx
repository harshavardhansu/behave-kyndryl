import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import {
  ArrowUpRight,
  Boxes,
  CheckCheck,
  CircleAlert,
  FileCheck2,
  KeyRound,
  ScanLine,
  Shield,
  ShieldCheck,
  ShieldOff,
} from 'lucide-react'
import { useWorkspace } from '../context'
import { request } from '../lib/api'
import { errorMessage, severities } from '../lib/format'
import type { SecurityFinding } from '../types'
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  KeyValue,
  Metric,
  Notice,
  PageHeader,
  Select,
  Tabs,
} from '../components/ui'

const scanners = [
  'All findings',
  'Static analysis',
  'Dependency scanning',
  'Secret scanning',
  'Container scanning',
  'Infrastructure as Code',
  'Authorization',
  'Policy violations',
]

function Triage({
  finding,
  onSaved,
}: {
  finding: SecurityFinding
  onSaved: () => void
}) {
  const { can, refresh, notify } = useWorkspace()
  const [status, setStatus] = useState(finding.status)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await request(`/security/${finding.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status, reason }),
      })
      await refresh()
      notify('Security triage decision recorded in the audit trail.')
      onSaved()
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="form-body triage-form" onSubmit={submit}>
      <h3 className="detail-section-title">Review decision</h3>
      <label className="field-label">
        Finding status
        <Select
          label="Finding status"
          value={status}
          onChange={(event) =>
            setStatus(event.target.value as SecurityFinding['status'])
          }
        >
          {['Open', 'Investigating', 'Resolved', 'Accepted risk'].map(
            (value) => (
              <option key={value}>{value}</option>
            )
          )}
        </Select>
      </label>
      <label className="field-label">
        Review reason
        <textarea
          required
          minLength={10}
          maxLength={2000}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      {!can('security:review') && (
        <Notice title="Security review permission required" tone="warning">
          The current role can inspect findings but cannot change a triage
          decision.
        </Notice>
      )}
      {error && (
        <Notice title="Review not recorded" tone="error">
          {error}
        </Notice>
      )}
      <Button
        type="submit"
        variant="primary"
        disabled={!can('security:review')}
        busy={busy}
      >
        <ShieldCheck size={18} />
        Save triage
      </Button>
    </form>
  )
}

export function Security() {
  const { data } = useWorkspace()
  const [params] = useSearchParams()
  const [category, setCategory] = useState('All findings')
  const [severity, setSeverity] = useState('All severities')
  const [status, setStatus] = useState('All statuses')
  const [selectedId, setSelectedId] = useState<string | null>(
    params.get('finding')
  )
  const [sbom, setSbom] = useState(false)
  const selected = data.security.find((finding) => finding.id === selectedId)
  const rows = data.security.filter(
    (finding) =>
      (category === 'All findings' || finding.category === category) &&
      (severity === 'All severities' || finding.severity === severity) &&
      (status === 'All statuses' || finding.status === status)
  )
  const open = data.security.filter((finding) => finding.status !== 'Resolved')
  const columns: ColumnDef<SecurityFinding>[] = [
    {
      accessorKey: 'title',
      header: 'Security finding',
      cell: ({ row }) => (
        <div className="incident-cell">
          <span className="mono record-id">
            {row.original.id} / {row.original.category}
          </span>
          <strong>{row.original.title}</strong>
        </div>
      ),
    },
    {
      accessorKey: 'severity',
      header: 'Severity',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    {
      accessorKey: 'status',
      header: 'Triage status',
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
      accessorKey: 'file',
      header: 'Source reference',
      cell: ({ row }) => (
        <span className="mono table-mono">
          {row.original.file}:{row.original.line}
        </span>
      ),
    },
    {
      accessorKey: 'reference',
      header: 'Scanner reference',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{String(getValue())}</span>
      ),
    },
  ]
  return (
    <div className="page-enter">
      <PageHeader
        title="Security centre"
        description="Workspace findings / All environments / Synthetic scanner evidence"
        actions={
          <>
            <Button onClick={() => setSbom(true)}>
              <Boxes size={15} />
              Demo SBOM
            </Button>
            <Link to="/administration" className="button button-secondary">
              <ScanLine size={15} />
              Configure scanners
              <ArrowUpRight size={13} />
            </Link>
          </>
        }
      />
      <div className="metrics-grid four">
        <Metric
          label="Critical findings"
          value={open
            .filter((finding) => finding.severity === 'Critical')
            .length.toString()
            .padStart(2, '0')}
          detail="Unresolved findings block release"
          icon={ShieldOff}
          critical
        />
        <Metric
          label="High severity"
          value={open
            .filter((finding) => finding.severity === 'High')
            .length.toString()
            .padStart(2, '0')}
          detail="Prioritized human triage"
          icon={CircleAlert}
        />
        <Metric
          label="Under review"
          value={open
            .filter((finding) => finding.status === 'Investigating')
            .length.toString()
            .padStart(2, '0')}
          detail="Assigned security investigations"
          icon={Shield}
        />
        <Metric
          label="Resolved"
          value={data.security
            .filter((finding) => finding.status === 'Resolved')
            .length.toString()
            .padStart(2, '0')}
          detail="Recorded fixture outcomes"
          icon={CheckCheck}
        />
      </div>
      <Notice title="No security scanner is connected" tone="warning">
        These are synthetic scanner findings. No SAST, dependency, secret,
        container or infrastructure scan has been executed by this workspace.
      </Notice>
      <div className="section-spacer" />
      <Tabs items={scanners} value={category} onChange={setCategory} />
      <DataTable
        data={rows}
        columns={columns}
        onRowClick={(finding) => setSelectedId(finding.id)}
        searchPlaceholder="Search findings, files or services"
        toolbar={
          <>
            <Select
              label="Security severity filter"
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              <option>All severities</option>
              {severities.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </Select>
            <Select
              label="Security triage status filter"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              {[
                'All statuses',
                'Open',
                'Investigating',
                'Resolved',
                'Accepted risk',
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </Select>
          </>
        }
        emptyTitle="No matching finding records"
        emptyDescription="No fixture findings match this category. This does not imply a successful or clean security scan."
      />
      <div className="security-principles">
        <div>
          <KeyRound size={19} />
          <strong>Secrets redacted</strong>
          <p>Potential credentials are masked before local evidence storage.</p>
        </div>
        <div>
          <ShieldCheck size={19} />
          <strong>Mandatory release gate</strong>
          <p>Open critical findings cannot be bypassed by accepting risk.</p>
        </div>
        <div>
          <FileCheck2 size={19} />
          <strong>Audited human decisions</strong>
          <p>Triage changes require a security role and a recorded reason.</p>
        </div>
      </div>
      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelectedId(null)}
        title={selected?.title ?? 'Security finding'}
        subtitle={selected?.id}
      >
        {selected && (
          <>
            <div className="detail-badges">
              <Badge>{selected.severity}</Badge>
              <Badge>{selected.status}</Badge>
              <Badge tone="outline">Synthetic finding</Badge>
            </div>
            <p className="body-copy">{selected.description}</p>
            <dl>
              <KeyValue label="Category">{selected.category}</KeyValue>
              <KeyValue label="Affected service" mono>
                {selected.service}
              </KeyValue>
              <KeyValue label="Source file" mono>
                {selected.file}:{selected.line}
              </KeyValue>
              <KeyValue label="Scanner reference" mono>
                {selected.reference}
              </KeyValue>
              <KeyValue label="Linked incident">
                {selected.incidentId || 'No linked incident'}
              </KeyValue>
            </dl>
            <h3 className="detail-section-title">Remediation guidance</h3>
            <p className="body-copy">{selected.guidance}</p>
            <Triage
              key={selected.id}
              finding={selected}
              onSaved={() => setSelectedId(null)}
            />
          </>
        )}
      </Drawer>
      <Drawer
        open={sbom}
        onClose={() => setSbom(false)}
        title="Software bill of materials"
        subtitle="Example inventory / Not a generated SBOM"
      >
        <Notice title="Partial synthetic inventory">
          These declared dependencies are fixture metadata, not a verified scan
          or a complete dependency graph.
        </Notice>
        <dl>
          <KeyValue label="Service">commerce-checkout</KeyValue>
          <KeyValue label="Runtime">Java 21 / Eclipse Temurin</KeyValue>
          <KeyValue label="Framework">Spring Boot 3.3.5 (fixture)</KeyValue>
          <KeyValue label="Database driver">
            PostgreSQL JDBC (version not provided)
          </KeyValue>
          <KeyValue label="Connection pool">
            HikariCP (managed dependency)
          </KeyValue>
          <KeyValue label="Test framework">JUnit (managed dependency)</KeyValue>
          <KeyValue label="License verification">Not performed</KeyValue>
          <KeyValue label="Full SBOM artifact">
            Unavailable until an SCA adapter is configured
          </KeyValue>
        </dl>
        <Link
          className="button button-secondary"
          to="/administration"
          onClick={() => setSbom(false)}
        >
          Scanner configuration
          <ArrowUpRight size={14} />
        </Link>
      </Drawer>
    </div>
  )
}

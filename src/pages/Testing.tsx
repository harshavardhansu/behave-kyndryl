import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import {
  ArrowRight,
  CheckCheck,
  CircleX,
  ClipboardCheck,
  FilePlus2,
  FlaskConical,
  Gauge,
  Play,
  ShieldCheck,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import { post } from '../lib/api'
import type { TestRun } from '../types'
import { dateTime, errorMessage } from '../lib/format'
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  KeyValue,
  Metric,
  Modal,
  Notice,
  PageHeader,
  SectionHeader,
  Select,
  Tabs,
} from '../components/ui'
import {
  EvidenceLinks,
  GateList,
  IncidentSelector,
} from '../components/incident'

const categories = [
  'All categories',
  'Unit',
  'Integration',
  'API',
  'End-to-end',
  'Regression',
  'Contract',
  'Performance',
  'Load & stress',
  'Security',
  'Static analysis',
  'Dependency scanning',
  'Infrastructure',
  'Configuration',
  'Database migration',
  'Smoke',
  'Post-deployment',
  'Manually recorded',
]

export function Testing() {
  const { data, can, setActionDialog, refresh, notify } = useWorkspace()
  const incident = useIncident()
  const [params] = useSearchParams()
  const [tab, setTab] = useState('Test runs')
  const [status, setStatus] = useState('All statuses')
  const [category, setCategory] = useState('All categories')
  const [selectedId, setSelectedId] = useState<string | null>(params.get('run'))
  const [recordOpen, setRecordOpen] = useState(false)
  const [form, setForm] = useState({
    suite: '',
    commit: '',
    passed: 0,
    failed: 0,
    skipped: 0,
    duration: 0,
    source: '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!incident) return <EmptyState title="No incident selected" />
  const tests = data.tests
    .filter((test) => test.incidentId === incident.id)
    .sort((first, second) => second.timestamp.localeCompare(first.timestamp))
  const passed = tests.reduce((total, test) => total + test.passed, 0)
  const failed = tests.reduce((total, test) => total + test.failed, 0)
  const skipped = tests.reduce((total, test) => total + test.skipped, 0)
  const change = data.changes.find(
    (record) => record.incidentId === incident.id
  )
  const selected = data.tests.find((test) => test.id === selectedId)
  const canValidate =
    can('validation:run', incident.environment) &&
    ['Fix Proposed', 'Testing', 'Root Cause Identified'].includes(
      incident.status
    )
  const columns: ColumnDef<TestRun>[] = [
    {
      accessorKey: 'suite',
      header: 'Test suite',
      cell: ({ row }) => (
        <div className="incident-cell">
          <span className="mono record-id">{row.original.id}</span>
          <strong>{row.original.suite}</strong>
          <small>
            {row.original.synthetic ? 'Synthetic fixture' : 'Manually recorded'}
          </small>
        </div>
      ),
    },
    { accessorKey: 'category', header: 'Category' },
    {
      accessorKey: 'status',
      header: 'Result',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    {
      id: 'results',
      header: 'Passed / failed / skipped',
      accessorFn: (test) => `${test.passed} / ${test.failed} / ${test.skipped}`,
      cell: ({ getValue }) => (
        <span className="mono">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'duration',
      header: 'Duration',
      cell: ({ getValue }) => (
        <span className="mono">{String(getValue())}s</span>
      ),
    },
    {
      accessorKey: 'commit',
      header: 'Commit',
      cell: ({ getValue }) => (
        <span className="mono table-mono">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: 'timestamp',
      header: 'Recorded',
      cell: ({ getValue }) => (
        <span className="table-timestamp">{dateTime(String(getValue()))}</span>
      ),
    },
  ]
  async function record(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await post(`/incidents/${incident!.id}/tests`, form)
      await refresh()
      setRecordOpen(false)
      notify(
        'Test evidence recorded with its source. BEHAVE KYNDRYL did not execute these tests.'
      )
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="page-enter">
      <PageHeader
        title="Testing & validation"
        description="Quality gates / Reproducible evidence / Exact-commit validation"
        actions={
          <>
            <Button
              disabled={!can('validation:run', 'Staging')}
              onClick={() => {
                setForm((current) => ({
                  ...current,
                  commit: change?.commit ?? '',
                }))
                setRecordOpen(true)
              }}
            >
              <FilePlus2 size={15} />
              Record test results
            </Button>
            <Button
              variant="primary"
              disabled={!canValidate}
              title="A proposed fix and validation permission are required"
              onClick={() =>
                setActionDialog({
                  incidentId: incident.id,
                  action: 'run-validation',
                })
              }
            >
              <Play size={17} />
              Replay validation
            </Button>
          </>
        }
      />
      <div className="module-context-bar">
        <IncidentSelector />
        <Badge tone="outline">Runner not configured</Badge>
      </div>
      <div className="metrics-grid four">
        <Metric
          label="Total recorded checks"
          value={passed + failed + skipped}
          detail={`${tests.length} synthetic or recorded runs`}
          icon={FlaskConical}
        />
        <Metric
          label="Passed"
          value={passed}
          detail={`${skipped} skipped / ${tests.reduce((total, test) => total + test.flaky, 0)} flaky recorded`}
          icon={CheckCheck}
        />
        <Metric
          label="Failed"
          value={failed}
          detail="Failed mandatory gates block promotion"
          icon={CircleX}
          critical
        />
        <Metric
          label="Coverage"
          value="--"
          detail="Not measured / no connected runner"
          icon={Gauge}
        />
      </div>
      <Tabs
        items={['Test runs', 'Quality gates', 'Failure analysis']}
        value={tab}
        onChange={setTab}
      />
      {tab === 'Test runs' && (
        <>
          <DataTable
            data={tests.filter(
              (test) =>
                (status === 'All statuses' || test.status === status) &&
                (category === 'All categories' || test.category === category)
            )}
            columns={columns}
            onRowClick={(test) => setSelectedId(test.id)}
            searchPlaceholder="Search suites, commits or result IDs"
            toolbar={
              <>
                <Select
                  label="Test status filter"
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                >
                  {['All statuses', 'Passed', 'Failed', 'Running'].map(
                    (value) => (
                      <option key={value}>{value}</option>
                    )
                  )}
                </Select>
                <Select
                  label="Test category filter"
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  {categories.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </Select>
              </>
            }
          />
          <Notice title="No test execution is implied" tone="warning">
            Demo replay loads predefined synthetic results. Manually entered
            results retain their source reference. Executing code requires an
            isolated, configured runner with resource and network limits.
          </Notice>
        </>
      )}
      {tab === 'Quality gates' && (
        <div className="detail-grid">
          <section>
            <SectionHeader
              title="Mandatory promotion gates"
              caption={
                change
                  ? `${change.id} / ${change.commit}`
                  : 'No proposed change'
              }
            />
            {change ? (
              <GateList gates={change.gates} />
            ) : (
              <EmptyState
                title="No proposed change"
                description="A remediation proposal is required before readiness can be evaluated."
              />
            )}
            <div className="section-spacer" />
            <Button
              disabled={
                !change ||
                change.gates.some((gate) => !gate.passed) ||
                incident.status !== 'Testing' ||
                !can('approval:request', incident.environment)
              }
              onClick={() =>
                setActionDialog({
                  incidentId: incident.id,
                  action: 'request-approval',
                })
              }
            >
              <ShieldCheck size={15} />
              Request approval
            </Button>
          </section>
          <section className="detail-sidebar">
            <SectionHeader title="Validation policy" />
            <dl>
              <KeyValue label="Required pass rate">
                {data.policy.minimumPassRate}%
              </KeyValue>
              <KeyValue label="Critical findings">Must be resolved</KeyValue>
              <KeyValue label="Build & regression">
                Required for exact proposed commit
              </KeyValue>
              <KeyValue label="Performance">
                p95 below 500 ms in checkout fixture
              </KeyValue>
              <KeyValue label="Code review">Separate human approval</KeyValue>
              <KeyValue label="Production gate">
                Explicit authorization
              </KeyValue>
            </dl>
            <Link className="text-link" to="/administration">
              Policy administration
              <ArrowRight size={13} />
            </Link>
          </section>
        </div>
      )}
      {tab === 'Failure analysis' && (
        <>
          <SectionHeader
            title="Failed case excerpts"
            caption="Partial synthetic case details / full counts retained on the run"
          />
          <div className="failure-list">
            {tests.flatMap((test) =>
              test.cases
                .filter((testCase) => testCase.status === 'Failed')
                .map((testCase) => (
                  <button
                    key={`${test.id}-${testCase.name}`}
                    onClick={() => setSelectedId(test.id)}
                  >
                    <CircleX size={18} />
                    <div>
                      <strong>{testCase.name}</strong>
                      <p>{testCase.error}</p>
                      <small>
                        {test.id} / {test.commit} / {testCase.duration}s
                      </small>
                    </div>
                    <ArrowRight size={14} />
                  </button>
                ))
            )}
            {!failed && (
              <EmptyState
                title="No recorded failures"
                description="No failed check is present in the selected recorded runs. This is not a guarantee of defect-free software."
              />
            )}
          </div>
        </>
      )}
      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelectedId(null)}
        title={selected?.suite ?? 'Validation run'}
        subtitle={selected?.id}
      >
        {selected && (
          <>
            <div className="detail-badges">
              <Badge>{selected.status}</Badge>
              <Badge tone="outline">
                {selected.synthetic ? 'Synthetic result' : 'Manually recorded'}
              </Badge>
            </div>
            <Notice title="Result provenance">{selected.source}</Notice>
            <dl>
              <KeyValue label="Commit" mono>
                {selected.commit}
              </KeyValue>
              <KeyValue label="Environment">{selected.environment}</KeyValue>
              <KeyValue label="Recorded">
                {dateTime(selected.timestamp)}
              </KeyValue>
              <KeyValue label="Duration">
                {selected.duration}s{' '}
                {selected.synthetic ? '(fixture value)' : '(reported)'}
              </KeyValue>
              <KeyValue label="Pass / fail / skip">
                {selected.passed} / {selected.failed} / {selected.skipped}
              </KeyValue>
              <KeyValue label="Coverage">
                {selected.coverage === null
                  ? 'Not measured'
                  : `${selected.coverage}% (reported)`}
              </KeyValue>
            </dl>
            <h3 className="detail-section-title">Case excerpts</h3>
            <div className="test-case-details">
              {selected.cases.map((testCase) => (
                <div key={testCase.name}>
                  <div>
                    <strong className="mono">{testCase.name}</strong>
                    <Badge>{testCase.status}</Badge>
                  </div>
                  <dl>
                    <KeyValue label="Expected">{testCase.expected}</KeyValue>
                    <KeyValue label="Actual">{testCase.actual}</KeyValue>
                    <KeyValue label="Duration">{testCase.duration}s</KeyValue>
                  </dl>
                  {testCase.error && (
                    <pre className="evidence-excerpt">{testCase.error}</pre>
                  )}
                </div>
              ))}
              {!selected.cases.length && (
                <p className="muted">
                  The manual record contains counts only. Consult its source
                  report for individual cases.
                </p>
              )}
            </div>
            <h3 className="detail-section-title">Related evidence</h3>
            <EvidenceLinks
              ids={data.evidence
                .filter(
                  (record) =>
                    record.incidentId === selected.incidentId &&
                    record.type === 'Test'
                )
                .map((record) => record.id)}
            />
          </>
        )}
      </Drawer>
      <Modal
        open={recordOpen}
        onClose={() => !busy && setRecordOpen(false)}
        title="Record test evidence"
        description={`${incident.id} / Results from an external or manual run`}
      >
        <form onSubmit={record}>
          <div className="modal-body form-body">
            <label className="field-label">
              Suite name
              <input
                required
                minLength={5}
                value={form.suite}
                onChange={(event) =>
                  setForm({ ...form, suite: event.target.value })
                }
              />
            </label>
            <label className="field-label">
              Exact build or commit reference
              <input
                required
                minLength={3}
                value={form.commit}
                onChange={(event) =>
                  setForm({ ...form, commit: event.target.value })
                }
              />
            </label>
            <div className="form-grid three">
              {(['passed', 'failed', 'skipped'] as const).map((field) => (
                <label className="field-label" key={field}>
                  {field[0].toUpperCase() + field.slice(1)}
                  <input
                    type="number"
                    min="0"
                    max="1000000"
                    required
                    value={form[field]}
                    onChange={(event) =>
                      setForm({ ...form, [field]: Number(event.target.value) })
                    }
                  />
                </label>
              ))}
            </div>
            <label className="field-label">
              Duration in seconds
              <input
                type="number"
                min="0"
                max="86400"
                step="0.1"
                required
                value={form.duration}
                onChange={(event) =>
                  setForm({ ...form, duration: Number(event.target.value) })
                }
              />
            </label>
            <label className="field-label">
              Source report reference
              <input
                required
                minLength={10}
                value={form.source}
                onChange={(event) =>
                  setForm({ ...form, source: event.target.value })
                }
                placeholder="Pipeline run, report path or signed result artifact"
              />
            </label>
            <Notice title="Manual provenance">
              This records a reported result; it does not claim that BEHAVE KYNDRYL
              executed a test. Failed required checks block approval.
            </Notice>
            {error && (
              <Notice title="Result not recorded" tone="error">
                {error}
              </Notice>
            )}
          </div>
          <div className="modal-footer">
            <Button onClick={() => setRecordOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" busy={busy}>
              <ClipboardCheck size={18} />
              Record results
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import {
  ArrowRight,
  ArrowUpRight,
  Bell,
  Bot,
  Boxes,
  Check,
  ChevronRight,
  Clock3,
  Database,
  DatabaseBackup,
  FileKey2,
  GitBranch,
  Globe,
  KeyRound,
  LockKeyhole,
  Save,
  Server,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Unplug,
  Users,
} from 'lucide-react'
import { useWorkspace } from '../context'
import { post, request } from '../lib/api'
import { errorMessage } from '../lib/format'
import type { Integration, Policy, Service, Session } from '../types'
import {
  Avatar,
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  KeyValue,
  Modal,
  Notice,
  PageHeader,
  SectionHeader,
  Select,
  Tabs,
} from '../components/ui'

const integrationIcons: Record<string, typeof Bot> = {
  'AI provider': Bot,
  Identity: KeyRound,
  Telemetry: Database,
  Repository: GitBranch,
  Execution: Server,
  Security: ShieldCheck,
  Release: Globe,
  Evidence: Database,
}

function PolicyEditor() {
  const { data, can, refresh, notify } = useWorkspace()
  const [policy, setPolicy] = useState<Policy>(data.policy)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const editable = can('admin:write')
  async function save() {
    setBusy(true)
    setError('')
    try {
      await request('/admin/policy', {
        method: 'PUT',
        body: JSON.stringify(policy),
      })
      await refresh()
      setConfirm(false)
      notify(
        'Workspace policy saved. Mandatory separate approval and critical-finding gates remain enforced.'
      )
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          setConfirm(true)
        }}
        className="policy-form"
      >
        <SectionHeader
          title="Agent execution & quality gates"
          caption="Server-validated settings / administrator permission required"
          actions={
            <Button type="submit" variant="primary" disabled={!editable}>
              <Save size={18} />
              Save policy
            </Button>
          }
        />
        <div className="policy-fields">
          {(
            [
              {
                key: 'maxTaskSeconds',
                label: 'Workflow time budget',
                unit: 'seconds',
                description:
                  'Maximum wall-clock budget for a bounded demo investigation.',
                min: 10,
                max: 300,
              },
              {
                key: 'maxRetries',
                label: 'Retry budget',
                unit: 'retries',
                description:
                  'Failed and cancelled workflows can be retried only within this limit.',
                min: 0,
                max: 3,
              },
              {
                key: 'minimumPassRate',
                label: 'Required check pass rate',
                unit: '%',
                description:
                  'Minimum required check ratio. Any failed mandatory check still blocks promotion.',
                min: 95,
                max: 100,
              },
              {
                key: 'retentionDays',
                label: 'Declared retention period',
                unit: 'days',
                description:
                  'Policy metadata only. Automatic deletion is not enabled in the local demo.',
                min: 7,
                max: 365,
              },
            ] as const
          ).map((field) => (
            <label key={field.key}>
              <div>
                <strong>{field.label}</strong>
                <p>{field.description}</p>
              </div>
              <span className="number-setting">
                <input
                  type="number"
                  aria-label={field.label}
                  required
                  min={field.min}
                  max={field.max}
                  value={policy[field.key]}
                  disabled={!editable}
                  onChange={(event) =>
                    setPolicy({
                      ...policy,
                      [field.key]: Number(event.target.value),
                    })
                  }
                />
                <span>{field.unit}</span>
              </span>
            </label>
          ))}
        </div>
        <SectionHeader
          title="Mandatory safeguards"
          caption="These boundaries cannot be disabled by this configuration interface"
        />
        <div className="mandatory-policies">
          {[
            'Production operations require explicit authorization',
            'A different human approves the requested change',
            'Unresolved critical findings block release',
            'Untrusted content has no tool permissions',
            'Shell, arbitrary network and repository execution are disabled',
          ].map((label) => (
            <div key={label}>
              <span className="policy-check">
                <Check size={13} />
              </span>
              <strong>{label}</strong>
              <LockKeyhole size={13} />
            </div>
          ))}
        </div>
        {!editable && (
          <Notice title="Read-only policy access">
            The current role can inspect this policy. Only an Administrator can
            save changes; the API independently enforces this permission.
          </Notice>
        )}
      </form>
      <Modal
        open={confirm}
        onClose={() => !busy && setConfirm(false)}
        title="Confirm policy update"
        description="Workspace-wide / Audited configuration change"
      >
        <div className="modal-body form-body">
          <Notice title="This change affects future workflow attempts">
            The new task, retry and quality thresholds take effect on subsequent
            operations. Required production approval and separate human review
            remain mandatory.
          </Notice>
          <dl>
            <KeyValue label="Workflow budget">
              {policy.maxTaskSeconds} seconds
            </KeyValue>
            <KeyValue label="Retry budget">{policy.maxRetries}</KeyValue>
            <KeyValue label="Required pass rate">
              {policy.minimumPassRate}%
            </KeyValue>
            <KeyValue label="Retention declaration">
              {policy.retentionDays} days / no deletion job configured
            </KeyValue>
          </dl>
          {error && (
            <Notice title="Policy not changed" tone="error">
              {error}
            </Notice>
          )}
        </div>
        <div className="modal-footer">
          <Button onClick={() => setConfirm(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} onClick={() => void save()}>
            <Save size={18} />
            Confirm policy
          </Button>
        </div>
      </Modal>
    </>
  )
}

function DemoResetButton() {
  const { data, can, refresh, notify } = useWorkspace()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  if (data.mode !== 'demo' || !can('admin:write')) return null
  async function reset() {
    setBusy(true)
    try {
      const result = await post<{ message: string }>('/admin/demo-reset', {})
      await refresh()
      notify(result.message)
      setOpen(false)
    } catch (failure) {
      notify(errorMessage(failure), true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <DatabaseBackup size={15} /> Reset demo data
      </Button>
      <Modal open={open} onClose={() => !busy && setOpen(false)} title="Reset demo data" description="Restore the realistic demo stories for a fresh demo run.">
        <Notice title="What happens">
          Your current workspace data (incidents, missions, evidence, audit trail) is backed up to data/backups/ and replaced with
          the original demo stories. You stay signed in. The Payment API sandbox is stopped.
        </Notice>
        <div className="modal-footer">
          <Button onClick={() => setOpen(false)} disabled={busy}>Cancel</Button>
          <Button variant="primary" busy={busy} onClick={() => void reset()}>
            <DatabaseBackup size={15} /> Back up and reset
          </Button>
        </div>
      </Modal>
    </>
  )
}

export function Administration() {
  const { data, session, can, refresh } = useWorkspace()
  const [tab, setTab] = useState('Integrations')
  const [category, setCategory] = useState('All categories')
  const [selectedIntegration, setSelectedIntegration] =
    useState<Integration | null>(null)
  const [selectedRole, setSelectedRole] = useState<Session['user'] | null>(null)
  const access = useQuery({
    queryKey: ['access-catalog', session.user.id],
    queryFn: () =>
      request<{ roles: Session['user'][]; identitySource: string }>(
        '/admin/access'
      ),
    enabled: tab === 'Users & access' && can('admin:write'),
    retry: false,
  })
  const roleColumns: ColumnDef<Session['user']>[] = [
    {
      accessorKey: 'name',
      header: 'Demo identity',
      cell: ({ row }) => (
        <div className="owner-cell">
          <Avatar name={row.original.name} />
          <div>
            <strong>{row.original.name}</strong>
            <small className="block muted">{row.original.id}</small>
          </div>
        </div>
      ),
    },
    {
      accessorKey: 'role',
      header: 'Role',
      cell: ({ getValue }) => (
        <Badge tone="outline">{String(getValue())}</Badge>
      ),
    },
    {
      id: 'environments',
      header: 'Write environment scope',
      accessorFn: (user) => user.environments.join(', '),
    },
    {
      id: 'permissions',
      header: 'Explicit permissions',
      accessorFn: (user) => user.permissions.length,
    },
  ]
  const serviceColumns: ColumnDef<Service>[] = [
    {
      accessorKey: 'name',
      header: 'Service',
      cell: ({ getValue }) => (
        <strong className="mono table-mono">{String(getValue())}</strong>
      ),
    },
    { accessorKey: 'type', header: 'Type' },
    { accessorKey: 'environment', header: 'Environment' },
    {
      accessorKey: 'health',
      header: 'Snapshot health',
      cell: ({ getValue }) => <Badge>{String(getValue())}</Badge>,
    },
    {
      id: 'evidence',
      header: 'Evidence references',
      accessorFn: (service) => service.evidence.length,
    },
  ]
  return (
    <div className="page-enter">
      <PageHeader
        title="Administration"
        description="Workspace configuration / Least-privilege access / Integration boundaries"
        actions={
          <>
            <DemoResetButton />
            <Badge tone="outline">
              <Settings2 size={12} />
              {session.user.role}
            </Badge>
          </>
        }
      />
      <Tabs
        items={[
          'Integrations',
          'Users & access',
          'Agent policies',
          'Workspace',
          'Service catalog',
          'Retention & redaction',
          'Notifications',
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'Integrations' && (
        <>
          <SectionHeader
            title="Integration registry"
            caption="Configured boundaries / No connection is implied by a saved setting"
            actions={
              <Select
                label="Integration category"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                <option>All categories</option>
                {[
                  ...new Set(
                    data.integrations.map((integration) => integration.category)
                  ),
                ].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </Select>
            }
          />
          <div className="integration-list">
            {data.integrations
              .filter(
                (integration) =>
                  category === 'All categories' ||
                  integration.category === category
              )
              .map((integration) => {
                const Icon = integrationIcons[integration.category] ?? Unplug
                return (
                  <div key={integration.id}>
                    <span className="integration-icon">
                      <Icon size={22} />
                    </span>
                    <div>
                      <span className="eyebrow">{integration.category}</span>
                      <h3>{integration.name}</h3>
                      <p>{integration.description}</p>
                    </div>
                    <Badge
                      tone={
                        integration.status === 'Demo source'
                          ? 'success'
                          : 'outline'
                      }
                    >
                      {integration.status}
                    </Badge>
                    <Button onClick={() => setSelectedIntegration(integration)}>
                      Setup details
                      <ChevronRight size={13} />
                    </Button>
                  </div>
                )
              })}
          </div>
        </>
      )}
      {tab === 'Users & access' && (
        <>
          <Notice title="Local demo identity directory">
            Production identity must come from validated Entra app roles. This
            interface cannot create production users or grant external
            permissions. Demo personas are selected from the profile menu.
          </Notice>
          <div className="section-spacer" />
          <SectionHeader
            title={
              can('admin:write')
                ? 'Configured role catalog'
                : 'Your effective permissions'
            }
            caption={
              access.data?.identitySource ?? 'API-authenticated current session'
            }
          />
          {access.isLoading && <div className="skeleton" />}
          {access.error && (
            <Notice
              title="Role catalog unavailable"
              tone="error"
              action={
                <Button onClick={() => void access.refetch()}>Retry</Button>
              }
            >
              {errorMessage(access.error)}
            </Notice>
          )}
          <DataTable
            data={
              can('admin:write') ? (access.data?.roles ?? []) : [session.user]
            }
            columns={roleColumns}
            onRowClick={setSelectedRole}
            searchPlaceholder="Search identities or roles"
            pageSize={12}
          />
          <div className="section-spacer" />
          <Notice title="Environment selection does not grant authorization">
            Developer and QA demo roles have development/staging write scope.
            Production actions require an authorized operational role; approvals
            require a separate approver identity.
          </Notice>
        </>
      )}
      {tab === 'Agent policies' && <PolicyEditor key={session.user.id} />}
      {tab === 'Workspace' && (
        <div className="admin-workspace-grid">
          <section>
            <SectionHeader
              title="Northstar Commerce"
              caption="Local workspace / Single-tenant demo"
            />
            <dl>
              <KeyValue label="Workspace mode">{data.mode}</KeyValue>
              <KeyValue label="Frontend">React / TypeScript / Vite</KeyValue>
              <KeyValue label="API">FastAPI / Pydantic / REST v1</KeyValue>
              <KeyValue label="Persistence">
                SQLAlchemy / configured database
              </KeyValue>
              <KeyValue label="AI execution">
                Synthetic by default / no automatic model invocation
              </KeyValue>
              <KeyValue label="Available environments">
                Development, Staging, Production
              </KeyValue>
              <KeyValue label="Workspace isolation">
                Single workspace / authenticated read scope
              </KeyValue>
              <KeyValue label="Feature flags">
                No live deployment, shell or archive execution
              </KeyValue>
            </dl>
          </section>
          <section>
            <SectionHeader
              title="Configuration ownership"
              caption="Deployment settings remain outside the browser"
            />
            <div className="configuration-ownership">
              {[
                {
                  icon: KeyRound,
                  title: 'Identity & credentials',
                  text: 'Managed identity, environment configuration and Entra app roles. No secrets are stored in the frontend.',
                },
                {
                  icon: Bot,
                  title: 'Model & tool permissions',
                  text: 'Read-only structured assessment boundary. No model can grant itself access or execute repository instructions.',
                },
                {
                  icon: Boxes,
                  title: 'Workspace provisioning',
                  text: 'Multi-tenant provisioning and custom environment catalogs are not implemented in the local demo.',
                },
              ].map((item) => (
                <div key={item.title}>
                  <item.icon size={20} />
                  <div>
                    <h3>{item.title}</h3>
                    <p>{item.text}</p>
                  </div>
                </div>
              ))}
            </div>
            <Link
              className="button button-secondary"
              to="/api-reference"
            >
              Open API reference
              <ArrowUpRight size={14} />
            </Link>
          </section>
        </div>
      )}
      {tab === 'Service catalog' && (
        <>
          <SectionHeader
            title="Declared service inventory"
            caption="15-service synthetic checkout architecture / snapshot only"
          />
          <DataTable
            data={data.services}
            columns={serviceColumns}
            onRowClick={(service) => {
              window.location.assign(`/war-room?service=${service.id}`)
            }}
            searchPlaceholder="Search catalog services"
            pageSize={12}
          />
          <Notice title="Catalog source">
            This inventory is the supplied synthetic topology. A real catalog
            adapter must preserve source ownership, environment and evidence
            timestamps.
          </Notice>
        </>
      )}
      {tab === 'Retention & redaction' && (
        <>
          <SectionHeader
            title="Evidence handling policy"
            caption="Safe file ingestion / No archive extraction"
          />
          <div className="admin-workspace-grid">
            <dl>
              <KeyValue label="Accepted file types">
                UTF-8 .txt, .log, .json and .csv
              </KeyValue>
              <KeyValue label="Maximum file size">2 MB by default</KeyValue>
              <KeyValue label="Archive handling">
                Rejected / no extraction
              </KeyValue>
              <KeyValue label="Path traversal">
                Filename path components rejected
              </KeyValue>
              <KeyValue label="Secret storage">
                Redacted excerpts only; original secret-bearing content is not
                persisted
              </KeyValue>
              <KeyValue label="Source integrity">
                SHA-256 of uploaded source bytes
              </KeyValue>
              <KeyValue label="Timestamp handling">
                Original timestamps retained; ingestion time recorded separately
              </KeyValue>
              <KeyValue label="Declared retention">
                {data.policy.retentionDays} days
              </KeyValue>
            </dl>
            <section>
              <Notice
                title="Retention enforcement is not enabled"
                tone="warning"
              >
                The declared period is policy metadata. No automatic cleanup or
                retention scheduler runs in the local demo. Database backups,
                object lifecycle policies and tamper-resistant audit storage
                require deployment infrastructure.
              </Notice>
              <div className="section-spacer" />
              <Notice title="Redaction is defense in depth">
                Pattern-based redaction is not a guarantee that every sensitive
                value is detected. Do not upload real confidential information
                to this demonstration.
              </Notice>
              <div className="section-spacer" />
              <Button onClick={() => setTab('Agent policies')}>
                <SlidersHorizontal size={15} />
                View policy settings
              </Button>
            </section>
          </div>
        </>
      )}
      {tab === 'Notifications' && (
        <>
          <SectionHeader
            title="Notification delivery"
            caption="In-app decisions / Outbound channels not configured"
          />
          <div className="notification-settings">
            <div>
              <Bell size={22} />
              <div>
                <h3>In-app notification centre</h3>
                <p>
                  Pending approval requests and active critical incidents are
                  derived from persisted workspace records. Read status is saved
                  locally in this browser.
                </p>
              </div>
              <Badge tone="success">Available</Badge>
            </div>
            <div>
              <Users size={22} />
              <div>
                <h3>Team escalation & paging</h3>
                <p>
                  Email, Teams, Slack and on-call adapters are not connected.
                  Escalations are recorded in the audit trail without claiming
                  that a message was delivered.
                </p>
              </div>
              <Badge tone="outline">Not configured</Badge>
            </div>
            <div>
              <Clock3 size={22} />
              <div>
                <h3>Scheduled reports</h3>
                <p>
                  On-demand exports are available. No report delivery scheduler
                  is running.
                </p>
              </div>
              <Link className="text-link" to="/reports">
                Reports
                <ArrowRight size={13} />
              </Link>
            </div>
          </div>
        </>
      )}
      <Drawer
        open={Boolean(selectedIntegration)}
        onClose={() => setSelectedIntegration(null)}
        title={selectedIntegration?.name ?? 'Integration setup'}
        subtitle={selectedIntegration?.category}
      >
        {selectedIntegration && (
          <>
            <div className="detail-badges">
              <Badge tone="outline">{selectedIntegration.status}</Badge>
            </div>
            <p className="body-copy">{selectedIntegration.description}</p>
            <h3 className="detail-section-title">
              Required deployment configuration
            </h3>
            <div className="configuration-keys">
              {selectedIntegration.required.map((key) => (
                <div key={key}>
                  <FileKey2 size={15} />
                  <code>{key}</code>
                </div>
              ))}
              {!selectedIntegration.required.length && (
                <EmptyState
                  title="No external configuration required"
                  description="The synthetic fixture is available from the local database."
                />
              )}
            </div>
            <Notice title="Credentials stay outside this interface">
              Use environment variables or a managed secret store. No
              credentials, access tokens or private keys are requested or stored
              by these controls.
            </Notice>
            {selectedIntegration.id !== 'demo' && (
              <Notice title="Connection not verified">
                This adapter is not currently connected. Setup details are
                configuration guidance, not a successful connection test.
              </Notice>
            )}
            <div className="release-actions">
              <Button
                onClick={() => {
                  void refresh()
                  setSelectedIntegration(null)
                }}
              >
                <Check size={15} />
                Recheck registry
              </Button>
              <Link
                className="button button-secondary"
                to="/api-reference"
              >
                API reference
                <ArrowUpRight size={13} />
              </Link>
            </div>
          </>
        )}
      </Drawer>
      <Drawer
        open={Boolean(selectedRole)}
        onClose={() => setSelectedRole(null)}
        title={selectedRole?.role ?? 'Role permissions'}
        subtitle={selectedRole?.name}
      >
        {selectedRole && (
          <>
            <Notice title="Server-enforced permissions">
              Every consequential API operation checks the role and target
              environment. Hiding or disabling a button is not the security
              boundary.
            </Notice>
            <dl>
              <KeyValue label="Identity">{selectedRole.name}</KeyValue>
              <KeyValue label="Environment scope">
                {selectedRole.environments.join(', ')}
              </KeyValue>
            </dl>
            <h3 className="detail-section-title">
              Explicit capability allowlist
            </h3>
            <div className="permission-list">
              {selectedRole.permissions.map((permission) => (
                <div key={permission}>
                  <LockKeyhole size={13} />
                  <code>{permission}</code>
                </div>
              ))}
            </div>
          </>
        )}
      </Drawer>
    </div>
  )
}

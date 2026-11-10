import { useDeferredValue, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  ArrowRight,
  BookOpen,
  CheckCheck,
  FilePenLine,
  FileText,
  Plus,
  ShieldCheck,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import { post } from '../lib/api'
import { dateTime, errorMessage } from '../lib/format'
import type { KnowledgeRecord } from '../types'
import {
  Badge,
  Button,
  EmptyState,
  KeyValue,
  Modal,
  Notice,
  PageHeader,
  SearchInput,
  Select,
  Tabs,
} from '../components/ui'

const knowledgeTypes = [
  'Runbook',
  'Troubleshooting guide',
  'Service documentation',
  'Architecture document',
  'Incident report',
  'Known error pattern',
  'Remediation procedure',
  'Release checklist',
  'Technical FAQ',
]

export function Knowledge() {
  const { data, session, can, refresh, notify } = useWorkspace()
  const incident = useIncident()
  const [params] = useSearchParams()
  const [tab, setTab] = useState('All records')
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [type, setType] = useState('All types')
  const [selectedId, setSelectedId] = useState(params.get('record') ?? 'KB-101')
  const [createOpen, setCreateOpen] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [decision, setDecision] = useState('approve')
  const [reason, setReason] = useState('')
  const [form, setForm] = useState({
    title: '',
    type: 'Runbook',
    body: '',
    service: incident?.service ?? 'checkout-svc',
    incidentId: '',
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const records = data.knowledge.filter(
    (record) =>
      (tab === 'All records' ||
        (tab === 'Approved knowledge' ? record.approved : !record.approved)) &&
      (type === 'All types' || record.type === type) &&
      `${record.title} ${record.body} ${record.services.join(' ')} ${record.owner}`
        .toLowerCase()
        .includes(deferredSearch.toLowerCase())
  )
  const selected =
    records.find((record) => record.id === selectedId) ?? records[0]
  async function create(event: FormEvent) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const result = await post<KnowledgeRecord>('/knowledge', {
        title: form.title,
        type: form.type,
        body: form.body,
        services: form.service ? [form.service] : [],
        incidents: form.incidentId ? [form.incidentId] : [],
      })
      await refresh()
      setCreateOpen(false)
      setSelectedId(result.id)
      setTab('Drafts')
      setType('All types')
      setSearch('')
      notify(
        'Knowledge draft saved. A separate human review is required for approval.'
      )
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }
  async function review(event: FormEvent) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await post(`/knowledge/${selected.id}/review`, { decision, reason })
      await refresh()
      setReviewOpen(false)
      setTab('All records')
      notify('Knowledge review decision recorded.')
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="page-enter">
      <PageHeader
        title="Knowledge centre"
        description="Approved runbooks / Verified outcomes / Clearly labeled drafts"
        actions={
          <Button
            variant="primary"
            disabled={!can('incident:update')}
            onClick={() => {
              setError('')
              setCreateOpen(true)
            }}
          >
            <Plus size={18} />
            Create draft
          </Button>
        }
      />
      <div className="knowledge-summary">
        <div>
          <BookOpen size={19} />
          <strong>{data.knowledge.length}</strong>
          <span>knowledge records</span>
        </div>
        <div>
          <ShieldCheck size={19} />
          <strong>
            {data.knowledge.filter((record) => record.approved).length}
          </strong>
          <span>approved references</span>
        </div>
        <div>
          <FilePenLine size={19} />
          <strong>
            {data.knowledge.filter((record) => !record.approved).length}
          </strong>
          <span>drafts awaiting review</span>
        </div>
      </div>
      <Tabs
        items={['All records', 'Approved knowledge', 'Drafts']}
        value={tab}
        onChange={setTab}
      />
      <div className="knowledge-layout">
        <aside>
          <div className="knowledge-filters">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search knowledge"
            />
            <Select
              label="Knowledge type filter"
              value={type}
              onChange={(event) => setType(event.target.value)}
            >
              <option>All types</option>
              {[
                ...new Set([
                  ...knowledgeTypes,
                  ...data.knowledge.map((record) => record.type),
                ]),
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </Select>
          </div>
          <div className="knowledge-list">
            {records.map((record) => (
              <button
                key={record.id}
                className={selected?.id === record.id ? 'selected' : ''}
                onClick={() => setSelectedId(record.id)}
              >
                <span className="knowledge-document-icon">
                  {record.approved ? (
                    <BookOpen size={19} />
                  ) : (
                    <FilePenLine size={19} />
                  )}
                </span>
                <div>
                  <span className="eyebrow">{record.type}</span>
                  <strong>{record.title}</strong>
                  <small>
                    {record.owner} / v{record.version}
                  </small>
                  <Badge
                    tone={record.approved ? 'success' : 'outline'}
                    dot={false}
                  >
                    {record.approved ? 'Approved' : 'Draft'}
                  </Badge>
                </div>
              </button>
            ))}
            {!records.length && (
              <EmptyState
                title="No matching knowledge"
                description="No document matches the current type, status or search."
              />
            )}
          </div>
        </aside>
        <article className="knowledge-reader">
          {selected ? (
            <>
              <div className="knowledge-record-header">
                <div className="detail-badges">
                  <Badge tone="outline">{selected.id}</Badge>
                  <Badge>
                    {selected.approved ? 'Approved' : 'Unapproved draft'}
                  </Badge>
                </div>
                <h2>{selected.title}</h2>
                <p>
                  {selected.type} / v{selected.version} / {selected.owner}
                </p>
              </div>
              {!selected.approved && (
                <Notice title="Draft, not authoritative knowledge">
                  This record has not completed separate human review.
                  AI-generated or unverified outcomes must not be used as
                  approved resolution procedures.
                </Notice>
              )}
              <div className="knowledge-content">
                {selected.body.split('\n\n').map((paragraph, index) => {
                  const [heading, ...lines] = paragraph.split('\n')
                  return (
                    <section key={index}>
                      {lines.length ? (
                        <>
                          <h3>{heading}</h3>
                          {lines.map((line, lineIndex) => (
                            <p key={lineIndex}>{line}</p>
                          ))}
                        </>
                      ) : (
                        <p>{heading}</p>
                      )}
                    </section>
                  )
                })}
              </div>
              <div className="knowledge-provenance">
                <h3>Document provenance</h3>
                <dl>
                  <KeyValue label="Source">{selected.source}</KeyValue>
                  <KeyValue label="Last reviewed">
                    {dateTime(selected.reviewedAt)}
                  </KeyValue>
                  <KeyValue label="Services">
                    {selected.services.join(', ') || 'Workspace-wide'}
                  </KeyValue>
                  <KeyValue label="Linked incidents">
                    <div className="inline-links">
                      {selected.incidents.map((id) => (
                        <Link key={id} to={`/incidents/${id}`}>
                          {id}
                          <ArrowRight size={12} />
                        </Link>
                      ))}
                      {!selected.incidents.length && 'None linked'}
                    </div>
                  </KeyValue>
                  <KeyValue label="Access scope">
                    Current workspace / authenticated read access
                  </KeyValue>
                </dl>
              </div>
              {!selected.approved && (
                <div className="release-actions">
                  <Button
                    disabled={
                      !can('admin:write') ||
                      selected.owner === session.user.name
                    }
                    onClick={() => {
                      setError('')
                      setReason('')
                      setReviewOpen(true)
                    }}
                  >
                    <ShieldCheck size={15} />
                    Review knowledge draft
                  </Button>
                  <span className="muted small-copy">
                    Separate administrator review required
                  </span>
                </div>
              )}
            </>
          ) : (
            <EmptyState
              title="No document selected"
              description="No knowledge record is available for the current filters."
            />
          )}
        </article>
      </div>
      <Modal
        open={createOpen}
        onClose={() => !busy && setCreateOpen(false)}
        title="Create a knowledge draft"
        description="Human-authored / Separate approval required"
        wide
      >
        <form onSubmit={create}>
          <div className="modal-body form-body">
            <label className="field-label">
              Title
              <input
                required
                minLength={8}
                maxLength={180}
                value={form.title}
                onChange={(event) =>
                  setForm({ ...form, title: event.target.value })
                }
              />
            </label>
            <div className="form-grid">
              <label className="field-label">
                Record type
                <Select
                  label="Knowledge record type"
                  value={form.type}
                  onChange={(event) =>
                    setForm({ ...form, type: event.target.value })
                  }
                >
                  {knowledgeTypes.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </Select>
              </label>
              <label className="field-label">
                Related service
                <Select
                  label="Knowledge related service"
                  value={form.service}
                  onChange={(event) =>
                    setForm({ ...form, service: event.target.value })
                  }
                >
                  <option value="">Workspace-wide</option>
                  {data.services.map((service) => (
                    <option key={service.id} value={service.id}>
                      {service.name}
                    </option>
                  ))}
                </Select>
              </label>
            </div>
            <label className="field-label">
              Related incident
              <Select
                label="Knowledge related incident"
                value={form.incidentId}
                onChange={(event) =>
                  setForm({ ...form, incidentId: event.target.value })
                }
              >
                <option value="">No linked incident</option>
                {data.incidents.map((record) => (
                  <option key={record.id} value={record.id}>
                    {record.id} / {record.title}
                  </option>
                ))}
              </Select>
            </label>
            <label className="field-label">
              Document body
              <textarea
                required
                minLength={30}
                maxLength={30000}
                rows={10}
                value={form.body}
                onChange={(event) =>
                  setForm({ ...form, body: event.target.value })
                }
              />
            </label>
            {error && (
              <Notice title="Draft not saved" tone="error">
                {error}
              </Notice>
            )}
          </div>
          <div className="modal-footer">
            <Button onClick={() => setCreateOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" busy={busy}>
              <FileText size={18} />
              Save draft
            </Button>
          </div>
        </form>
      </Modal>
      <Modal
        open={reviewOpen}
        onClose={() => !busy && setReviewOpen(false)}
        title="Review knowledge record"
        description={selected?.title}
      >
        <form onSubmit={review}>
          <div className="modal-body form-body">
            <label className="field-label">
              Decision
              <Select
                label="Knowledge approval decision"
                value={decision}
                onChange={(event) => setDecision(event.target.value)}
              >
                <option value="approve">Approve document</option>
                <option value="reject">Return for revision</option>
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
            <Notice title="Resolution verification required">
              Incident reports can only become approved knowledge when linked
              incidents are closed and recovery evidence is recorded. Synthetic
              outcomes remain demo-only.
            </Notice>
            {error && (
              <Notice title="Review not recorded" tone="error">
                {error}
              </Notice>
            )}
          </div>
          <div className="modal-footer">
            <Button onClick={() => setReviewOpen(false)}>Cancel</Button>
            <Button type="submit" variant="primary" busy={busy}>
              <CheckCheck size={18} />
              Record review
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}

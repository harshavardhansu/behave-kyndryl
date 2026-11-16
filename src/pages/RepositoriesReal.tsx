import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { ArrowRight, Boxes, Braces, ChevronRight, Code2, FileCode2, FileSearch, Folder, GitBranch, ShieldCheck } from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import { post, request } from '../lib/api'
import { dateTime, errorMessage } from '../lib/format'
import type { DependencyInventory, ProjectProfile, RepositoryAnalysis, RepositoryFinding } from '../types'
import { Badge, Button, DataTable, EmptyState, KeyValue, Metric, Notice, PageHeader, SectionHeader, Tabs } from '../components/ui'
import { IncidentSelector } from '../components/incident'

interface SourceInfo {
  label: string
  files: string[]
  total: number
  project: ProjectProfile | null
  pullRequests: boolean
  problem: string
}

const SCOPES = ['Security', 'Configuration', 'Code paths'] as const

/**
 * Project & repositories in a real workspace: the source code actually connected to the selected incident
 * (an uploaded file or ZIP, or a GitHub repository), browsable read-only, with scans by the built-in rules.
 */
export function RepositoriesReal() {
  const { data, refresh, notify, can } = useWorkspace()
  const incident = useIncident()
  const [tab, setTab] = useState('Project overview')
  const [filePath, setFilePath] = useState('')
  const [busy, setBusy] = useState(false)
  const [finding, setFinding] = useState<RepositoryFinding | null>(null)
  const id = incident?.id

  const source = useQuery({ queryKey: ['source', id, incident?.sourceUploads?.length ?? 0], queryFn: () => request<SourceInfo>(`/incidents/${id}/source`), enabled: Boolean(id) })
  const dependencies = useQuery({ queryKey: ['dependencies', id], queryFn: () => request<DependencyInventory>(`/incidents/${id}/dependencies`), enabled: Boolean(id) })
  const info = source.data
  const files = info?.files ?? []
  const selectedPath = files.includes(filePath) ? filePath : (files.find((path) => (info?.project?.entryPoints ?? []).includes(path)) ?? files[0] ?? '')
  const file = useQuery({
    queryKey: ['source-file', id, selectedPath],
    queryFn: () => request<{ path: string; lines: number; truncated: boolean; text: string }>(`/incidents/${id}/source/file?path=${encodeURIComponent(selectedPath)}`),
    enabled: Boolean(id && selectedPath && tab === 'Source explorer'),
  })
  const analyses = (data.analyses ?? []).filter((record) => record.incidentId === id).sort((first, second) => second.timestamp.localeCompare(first.timestamp))
  const latest = analyses[0]
  const highlighted = new Map((latest?.findings ?? []).filter((item) => item.file === selectedPath).map((item) => [item.line, item.title]))

  async function scan() {
    if (!id) return
    setBusy(true)
    try {
      const result = await post<RepositoryAnalysis>('/repositories/analyses', { source: 'incident', incidentId: id, scope: SCOPES, environment: 'Staging', permissionConfirmed: true })
      await refresh()
      setTab('Scan findings')
      notify(`Scanned the real files: ${result.findings.length} finding(s). Each names the file and line to check.`)
    } catch (failure) {
      notify(errorMessage(failure), true)
    } finally {
      setBusy(false)
    }
  }

  const columns: ColumnDef<RepositoryFinding>[] = [
    {
      accessorKey: 'title',
      header: 'Finding',
      cell: ({ row }) => (
        <div className="incident-cell">
          <span className="mono record-id">{row.original.id} / {row.original.category}</span>
          <strong>{row.original.title}</strong>
        </div>
      ),
    },
    { accessorKey: 'severity', header: 'Severity', cell: ({ getValue }) => <Badge>{String(getValue())}</Badge> },
    { accessorKey: 'file', header: 'Source reference', cell: ({ row }) => <span className="mono source-reference">{row.original.file}:{row.original.line}</span> },
  ]

  if (!incident)
    return <EmptyState title="No incident yet" description="Create an incident and give it source code (a file, a project ZIP or a GitHub repository). Its files appear here." icon={FileSearch} />

  const project = info?.project
  return (
    <div className="page-enter">
      <PageHeader
        title="Project & repositories"
        description="The source code connected to the selected incident / Read-only"
        actions={
          <Button variant="primary" busy={busy} disabled={!files.length || !can('workflow:run', 'Staging')} title={files.length ? 'Run the built-in rules on these files' : 'This incident has no source code yet'} onClick={() => void scan()}>
            <FileSearch size={18} />
            Scan this source
          </Button>
        }
      />
      <div className="module-context-bar">
        <IncidentSelector />
        <Badge tone="outline">{info?.pullRequests ? 'Pull requests on' : 'Read-only'}</Badge>
      </div>
      {source.isLoading && <p className="body-copy">Reading the connected source…</p>}
      {info && !files.length && (
        <Notice title="No source code is connected to this incident" tone="warning">
          {info.problem} Upload the affected file or a project ZIP as evidence on the incident, or create the incident with a GitHub repository. The agents can
          diagnose from logs without it, but they cannot produce or check a code change.
        </Notice>
      )}
      {info && files.length > 0 && (
        <>
          <div className="repository-identity">
            <span className="repository-mark"><GitBranch size={28} /></span>
            <div>
              <span className="eyebrow">{incident.service} / {incident.id}</span>
              <h2>{info.label}</h2>
              <p>
                {[project?.languages.slice(0, 3).map((item) => item.name).join(', '), project?.frameworks.join(', ')].filter(Boolean).join(' / ') || 'Language not recognised from the files'}
              </p>
            </div>
            <div className="repository-refs">
              {incident.repository?.ref && <span className="mono"><GitBranch size={13} />{incident.repository.ref.length > 20 ? incident.repository.ref.slice(0, 7) : incident.repository.ref}</span>}
              <Badge tone="outline">{info.label.startsWith('GitHub') ? 'Read from GitHub' : 'Uploaded by a person'}</Badge>
            </div>
          </div>
          <div className="metrics-grid four">
            <Metric label="Source files" value={info.total} detail="Readable source and configuration files" icon={Code2} />
            <Metric label="Declared dependencies" value={dependencies.data?.total ?? '--'} detail={dependencies.data ? `${dependencies.data.manifests.length} manifest file(s)` : 'Reading manifests'} icon={Boxes} />
            <Metric label="Scan findings" value={latest ? latest.findings.length : '--'} detail={latest ? `Scanned ${dateTime(latest.timestamp)}` : 'Not scanned yet'} icon={FileSearch} />
            <Metric label="Test files" value={project?.tests.files ?? 0} detail={project?.tests.frameworks.join(', ') || 'No test framework recognised'} icon={ShieldCheck} />
          </div>
          <Tabs items={['Project overview', 'Source explorer', 'Scan findings', 'Scan history']} value={tab} onChange={setTab} />
          {tab === 'Project overview' && (
            <>
              <div className="repository-overview-grid">
                <section>
                  <SectionHeader title="Files" caption={`${info.total} files${info.total > files.length ? ` / first ${files.length} listed` : ''}`} />
                  <div className="project-file-list">
                    {files.slice(0, 40).map((path) => (
                      <button key={path} onClick={() => { setFilePath(path); setTab('Source explorer') }}>
                        <FileCode2 size={17} />
                        <span className="mono">{path}</span>
                        <ChevronRight size={14} />
                      </button>
                    ))}
                  </div>
                  {files.length > 40 && <p className="muted">Open the Source explorer for all {files.length} files.</p>}
                </section>
                <section>
                  <SectionHeader title="What this project is" caption="Worked out from its files, nothing assumed" />
                  <dl>
                    <KeyValue label="Languages">{project?.languages.map((item) => `${item.name} (${item.files})`).join(', ') || 'Not recognised'}</KeyValue>
                    <KeyValue label="Frameworks">{project?.frameworks.join(', ') || 'None recognised'}</KeyValue>
                    <KeyValue label="Entry points" mono>{project?.entryPoints.join(', ') || 'None recognised'}</KeyValue>
                    <KeyValue label="Dependency files" mono>{project?.manifests.join(', ') || 'None found'}</KeyValue>
                    <KeyValue label="Tests">{project?.tests.files ? `${project.tests.files} file(s)${project.tests.frameworks.length ? ` / ${project.tests.frameworks.join(', ')}` : ''}` : 'No test files found'}</KeyValue>
                    <KeyValue label="Fix delivery">{info.pullRequests ? 'An approved fix is opened as a pull request on a new branch' : 'An approved fix is shown as a checked diff for the owning team to apply'}</KeyValue>
                  </dl>
                  {dependencies.data && dependencies.data.total > 0 && (
                    <>
                      <h3 className="detail-section-title">Declared dependencies</h3>
                      <p className="body-copy">
                        {dependencies.data.dependencies.slice(0, 14).map((row) => `${row.name} ${row.version}`).join(' · ')}
                        {dependencies.data.total > 14 ? ` · and ${dependencies.data.total - 14} more` : ''}
                      </p>
                    </>
                  )}
                </section>
              </div>
              <Notice title="What happens with this source">
                Agents read these files through read-only tools during a mission, and every read is recorded. The scan runs built-in rules on the same files. Nothing here
                is executed: no build, no tests.
              </Notice>
            </>
          )}
          {tab === 'Source explorer' && (
            <div className="source-explorer">
              <aside>
                <div className="source-tree-heading"><Folder size={16} />{info.total} files</div>
                {files.map((path) => (
                  <button className={path === selectedPath ? 'selected' : ''} key={path} onClick={() => setFilePath(path)} title={path}>
                    <FileCode2 size={14} />
                    <span>{path}</span>
                  </button>
                ))}
              </aside>
              <section>
                <div className="source-file-header">
                  <Braces size={16} />
                  <span className="mono">{selectedPath}</span>
                  <Badge tone="outline">{file.data ? `${file.data.lines} lines${file.data.truncated ? ' / shortened' : ''}` : 'Reading'}</Badge>
                </div>
                {file.isError && <Notice title="File could not be read" tone="warning">{errorMessage(file.error)}</Notice>}
                <pre className="source-code">
                  {(file.data?.text ?? '').split('\n').map((line, index) => (
                    <span key={index} className={highlighted.has(index + 1) ? 'highlighted-line' : ''} title={highlighted.get(index + 1)}>
                      <i>{index + 1}</i>
                      {line || ' '}
                      <br />
                    </span>
                  ))}
                </pre>
                {highlighted.size > 0 && <p className="muted">Highlighted lines have a finding from the latest scan. Secrets are masked.</p>}
              </section>
            </div>
          )}
          {tab === 'Scan findings' &&
            (latest ? (
              <>
                <Notice title="Built-in rules on the real files">{latest.limitations}</Notice>
                <div className="section-spacer" />
                <DataTable data={latest.findings} columns={columns} onRowClick={setFinding} searchPlaceholder="Search findings or source paths" emptyTitle="The rules matched nothing" emptyDescription="No rule matched these files. That is not proof the project is secure or correct." />
                {finding && (
                  <Notice title={`${finding.title} / ${finding.file}:${finding.line}`}>
                    {finding.evidence[0]} {finding.guidance}{' '}
                    <button className="text-link" onClick={() => { setFilePath(finding.file); setTab('Source explorer') }}>
                      Open the file <ArrowRight size={12} />
                    </button>
                  </Notice>
                )}
              </>
            ) : (
              <EmptyState title="Not scanned yet" description="Run the built-in rules on this incident's files. Security findings also appear in the Security centre." icon={FileSearch}
                action={<Button busy={busy} onClick={() => void scan()}><FileSearch size={15} />Scan this source</Button>} />
            ))}
          {tab === 'Scan history' && (
            <div className="analysis-history">
              {analyses.map((record) => (
                <button key={record.id} onClick={() => setTab('Scan findings')}>
                  <FileSearch size={19} />
                  <div>
                    <strong>{record.id}</strong>
                    <small>{dateTime(record.timestamp)} / {record.source}</small>
                  </div>
                  <Badge>{record.status}</Badge>
                  <span>{record.findings.length} findings</span>
                  <ArrowRight size={15} />
                </button>
              ))}
              {!analyses.length && <EmptyState title="No scans yet" description="No scan has been run for this incident." />}
            </div>
          )}
        </>
      )}
    </div>
  )
}

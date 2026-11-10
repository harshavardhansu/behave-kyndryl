import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import {
  ArrowRight,
  ArrowUpRight,
  Boxes,
  Braces,
  ChevronRight,
  Code2,
  FileCode2,
  FileSearch,
  Folder,
  GitBranch,
  GitCommitHorizontal,
  LockKeyhole,
  Play,
  ShieldCheck,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import type { RepositoryAnalysis, RepositoryFinding } from '../types'
import { post } from '../lib/api'
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
import { EvidenceLinks, IncidentSelector } from '../components/incident'

const sourceFiles = [
  {
    path: 'src/main/resources/application-production.yml',
    start: 14,
    language: 'YAML',
    content:
      'spring:\n  datasource:\n    hikari:\n      minimum-idle: 5\n      maximum-pool-size: 10\n      connection-timeout: 2000\n      idle-timeout: 600000\n\nmanagement:\n  tracing:\n    sampling:\n      probability: 1.0',
  },
  {
    path: 'src/main/java/CheckoutService.java',
    start: 72,
    language: 'Java',
    content:
      'public CheckoutResult checkout(CheckoutRequest request) {\n    PaymentAuthorization authorization = payments.authorize(request);\n    validateAuthorization(authorization);\n    return persistOrder(request, authorization);\n}\n\nprivate CheckoutResult persistOrder(\n        CheckoutRequest request,\n        PaymentAuthorization authorization) {\n    try (Connection connection = dataSource.getConnection()) {\n        return orderRepository.save(connection, request, authorization);\n    } catch (SQLException exception) {\n        throw new CheckoutUnavailableException(exception);\n    }\n}',
  },
  {
    path: 'src/test/java/CheckoutServiceTest.java',
    start: 20,
    language: 'Java',
    content:
      'class CheckoutServiceTest {\n    @Test\n    void completesSingleCheckout() {\n        CheckoutResult result = service.checkout(validRequest());\n        assertThat(result.status()).isEqualTo(CONFIRMED);\n    }\n\n    @Test\n    void preservesPaymentCorrelation() {\n        assertThat(service.checkout(validRequest()).traceId()).isNotBlank();\n    }\n}',
  },
  {
    path: 'pom.xml',
    start: 1,
    language: 'XML',
    content:
      '<project>\n  <modelVersion>4.0.0</modelVersion>\n  <groupId>com.northstar</groupId>\n  <artifactId>checkout-service</artifactId>\n  <version>2.18.0</version>\n  <properties>\n    <java.version>21</java.version>\n    <spring-boot.version>3.3.5</spring-boot.version>\n  </properties>\n</project>',
  },
  {
    path: 'Dockerfile',
    start: 1,
    language: 'Dockerfile',
    content:
      'FROM eclipse-temurin:21-jre\nWORKDIR /app\nCOPY target/checkout-service.jar application.jar\nUSER 10001:10001\nEXPOSE 8080\nENTRYPOINT ["java", "-jar", "application.jar"]',
  },
]

export function Repositories() {
  const { data, refresh, notify, can } = useWorkspace()
  const incident = useIncident()
  const [tab, setTab] = useState('Project overview')
  const [filePath, setFilePath] = useState(sourceFiles[0].path)
  const [analysisOpen, setAnalysisOpen] = useState(false)
  const [source, setSource] = useState('fixture')
  const [repositoryUrl, setRepositoryUrl] = useState('')
  const [branch, setBranch] = useState('main')
  const [commit, setCommit] = useState('c7f4e21')
  const [stack, setStack] = useState('Java / Spring Boot')
  const [scope, setScope] = useState(['Configuration', 'Code paths', 'Tests'])
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [finding, setFinding] = useState<RepositoryFinding | null>(null)
  const analyses = data.analyses ?? []
  const latest = [...analyses]
    .filter((record) => record.incidentId === incident?.id)
    .sort((first, second) => second.timestamp.localeCompare(first.timestamp))[0]
  const file =
    sourceFiles.find((record) => record.path === filePath) ?? sourceFiles[0]
  const columns: ColumnDef<RepositoryFinding>[] = [
    {
      accessorKey: 'title',
      header: 'Finding',
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
      accessorKey: 'file',
      header: 'Source reference',
      cell: ({ row }) => (
        <span className="mono source-reference">
          {row.original.file}:{row.original.line}
        </span>
      ),
    },
    {
      accessorKey: 'confidence',
      header: 'Confidence',
      cell: ({ getValue }) => (
        <span className="mono">{Number(getValue()).toFixed(2)}</span>
      ),
    },
  ]
  async function analyze(event: FormEvent) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await post<RepositoryAnalysis>('/repositories/analyses', {
        source,
        url: repositoryUrl,
        branch,
        commit,
        stack,
        environment: 'Staging',
        scope,
        incidentId: incident?.id,
        permissionConfirmed: confirmed,
      })
      await refresh()
      setAnalysisOpen(false)
      setTab('Analysis findings')
      notify(
        'Synthetic source analysis replay recorded. No repository was accessed and no code was executed.'
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
        title="Project & repositories"
        description="Authorized source context / Read-only analysis"
        actions={
          <Button
            variant="primary"
            disabled={!can('workflow:run', 'Staging')}
            onClick={() => setAnalysisOpen(true)}
          >
            <FileSearch size={18} />
            Analyse project
          </Button>
        }
      />
      <div className="module-context-bar">
        <IncidentSelector />
        <Badge tone="outline">
          <LockKeyhole size={11} />
          Read-only source fixture
        </Badge>
      </div>
      <div className="repository-identity">
        <span className="repository-mark">
          <GitBranch size={28} />
        </span>
        <div>
          <span className="eyebrow">
            Northstar Commerce / Example repository
          </span>
          <h2>commerce-checkout</h2>
          <p>Java 21 / Spring Boot / Maven / Containerized service</p>
        </div>
        <div className="repository-refs">
          <span>
            <GitBranch size={13} />
            main
          </span>
          <span className="mono">
            <GitCommitHorizontal size={13} />
            c7f4e21
          </span>
          <Badge tone="outline">Synthetic fixture</Badge>
        </div>
      </div>
      <div className="metrics-grid four">
        <Metric
          label="Source excerpts"
          value={sourceFiles.length}
          detail="Explicitly supplied fixture files"
          icon={Code2}
        />
        <Metric
          label="Service boundary"
          value="01"
          detail="checkout-svc / REST API"
          icon={Boxes}
        />
        <Metric
          label="Analysis findings"
          value={latest?.findings.length ?? '--'}
          detail={
            latest
              ? `Replay ${dateTime(latest.timestamp)}`
              : 'No analysis replay recorded'
          }
          icon={FileSearch}
        />
        <Metric
          label="Execution access"
          value="Read only"
          detail="No repository or shell permissions"
          icon={ShieldCheck}
        />
      </div>
      <Tabs
        items={[
          'Project overview',
          'Source explorer',
          'Analysis findings',
          'Analysis history',
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'Project overview' && (
        <>
          <div className="repository-overview-grid">
            <section>
              <SectionHeader
                title="Project structure"
                caption="Five source excerpts / not a full repository checkout"
              />
              <div className="project-file-list">
                {sourceFiles.map((record) => (
                  <button
                    key={record.path}
                    onClick={() => {
                      setFilePath(record.path)
                      setTab('Source explorer')
                    }}
                  >
                    <FileCode2 size={17} />
                    <span className="mono">{record.path}</span>
                    <Badge tone="outline" dot={false}>
                      {record.language}
                    </Badge>
                    <ChevronRight size={14} />
                  </button>
                ))}
              </div>
            </section>
            <section>
              <SectionHeader
                title="Application context"
                caption="Declared fixture metadata"
              />
              <dl>
                <KeyValue label="Entry point">
                  CheckoutService.checkout
                </KeyValue>
                <KeyValue label="API endpoint" mono>
                  POST /api/v1/checkout
                </KeyValue>
                <KeyValue label="Database">PostgreSQL / HikariCP</KeyValue>
                <KeyValue label="Dependencies">
                  Payment service, RDS proxy, Kafka
                </KeyValue>
                <KeyValue label="Build system">Maven / Java 21</KeyValue>
                <KeyValue label="Test framework">
                  JUnit / synthetic case excerpts
                </KeyValue>
                <KeyValue label="Source access">
                  No external repository connection
                </KeyValue>
              </dl>
            </section>
          </div>
          <Notice
            title="Repository adapter not configured"
            tone="warning"
            action={
              <Link className="button button-secondary" to="/administration">
                Configure
                <ArrowUpRight size={13} />
              </Link>
            }
          >
            A repository URL does not grant access. External source analysis
            requires a scoped identity and repository allowlist. Archive
            extraction and code execution are disabled.
          </Notice>
        </>
      )}
      {tab === 'Source explorer' && (
        <div className="source-explorer">
          <aside>
            <div className="source-tree-heading">
              <Folder size={16} />
              commerce-checkout
            </div>
            {sourceFiles.map((record) => (
              <button
                className={record.path === file.path ? 'selected' : ''}
                key={record.path}
                onClick={() => setFilePath(record.path)}
              >
                <FileCode2 size={14} />
                <span>{record.path.split('/').pop()}</span>
              </button>
            ))}
          </aside>
          <section>
            <div className="source-file-header">
              <Braces size={16} />
              <span className="mono">{file.path}</span>
              <Badge tone="outline">Fixture excerpt</Badge>
            </div>
            <pre className="source-code">
              {file.content.split('\n').map((line, index) => (
                <span
                  key={index}
                  className={
                    file.path.endsWith('application-production.yml') &&
                    index === 4
                      ? 'highlighted-line'
                      : ''
                  }
                >
                  <i>{file.start + index}</i>
                  {line || ' '}
                  <br />
                </span>
              ))}
            </pre>
          </section>
        </div>
      )}
      {tab === 'Analysis findings' &&
        (latest ? (
          <>
            <Notice title="Synthetic analysis output">
              {latest.limitations}
            </Notice>
            <div className="section-spacer" />
            <DataTable
              data={latest.findings}
              columns={columns}
              onRowClick={setFinding}
              searchPlaceholder="Search findings or source paths"
            />
            <div className="source-note">
              Static analysis cannot identify every runtime failure. Confidence
              does not replace reproduction or validation.
            </div>
          </>
        ) : (
          <EmptyState
            title="No source analysis recorded"
            description="A read-only synthetic source replay is available. External analysis requires an authorized repository adapter."
            icon={FileSearch}
            action={
              <Button onClick={() => setAnalysisOpen(true)}>
                <Play size={15} />
                Analyse fixture
              </Button>
            }
          />
        ))}
      {tab === 'Analysis history' && (
        <div className="analysis-history">
          {analyses.map((record) => (
            <button
              key={record.id}
              onClick={() => {
                setTab('Analysis findings')
                notify(
                  `Selected source replay ${record.id}. Findings are predefined fixture outputs.`
                )
              }}
            >
              <FileSearch size={19} />
              <div>
                <strong>{record.id}</strong>
                <small>
                  {dateTime(record.timestamp)} / {record.stack} /{' '}
                  {record.commit}
                </small>
              </div>
              <Badge>{record.status}</Badge>
              <span>{record.findings.length} findings</span>
              <ArrowRight size={15} />
            </button>
          ))}
          {!analyses.length && (
            <EmptyState
              title="No analysis history"
              description="No source replay or external analysis has been recorded."
            />
          )}
        </div>
      )}
      <Modal
        open={analysisOpen}
        onClose={() => !busy && setAnalysisOpen(false)}
        title="Analyse project"
        description="Read-only access / no execution"
      >
        <form onSubmit={analyze}>
          <div className="modal-body form-body">
            <label className="field-label">
              Analysis source
              <Select
                label="Analysis source"
                value={source}
                onChange={(event) => {
                  setSource(event.target.value)
                  setError('')
                }}
              >
                <option value="fixture">Synthetic checkout fixture</option>
                <option value="repository">Authorized repository URL</option>
              </Select>
            </label>
            {source === 'repository' && (
              <label className="field-label">
                Repository URL
                <input
                  type="url"
                  required
                  value={repositoryUrl}
                  onChange={(event) => setRepositoryUrl(event.target.value)}
                  placeholder="https://your-provider/organization/repository"
                />
              </label>
            )}
            <div className="form-grid">
              <label className="field-label">
                Branch
                <input
                  value={branch}
                  onChange={(event) => setBranch(event.target.value)}
                  disabled={source === 'fixture'}
                  required
                />
              </label>
              <label className="field-label">
                Commit or pull request
                <input
                  value={commit}
                  onChange={(event) => setCommit(event.target.value)}
                  disabled={source === 'fixture'}
                  required
                />
              </label>
            </div>
            <label className="field-label">
              Project type
              <Select
                label="Project type"
                value={stack}
                disabled={source === 'fixture'}
                onChange={(event) => setStack(event.target.value)}
              >
                {[
                  'Java / Spring Boot',
                  'Python',
                  'Node.js / TypeScript',
                  '.NET',
                  'Go',
                  'PHP',
                  'Frontend application',
                  'REST / GraphQL API',
                  'Container / Infrastructure as Code',
                  'Database / Event-driven system',
                ].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </Select>
            </label>
            <div>
              <span className="field-label">Analysis scope</span>
              <div className="scope-checkboxes">
                {[
                  'Configuration',
                  'Code paths',
                  'Dependencies',
                  'Tests',
                  'Security',
                ].map((value) => (
                  <label className="checkbox-row" key={value}>
                    <input
                      type="checkbox"
                      checked={scope.includes(value)}
                      onChange={(event) =>
                        setScope((current) =>
                          event.target.checked
                            ? [...current, value]
                            : current.filter((item) => item !== value)
                        )
                      }
                    />
                    {value}
                  </label>
                ))}
              </div>
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                required
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>
                I am authorized to inspect this source and understand that no
                code will be executed.
              </span>
            </label>
            <Notice
              title={
                source === 'fixture'
                  ? 'Synthetic analysis replay'
                  : 'External adapter unavailable'
              }
            >
              {source === 'fixture'
                ? 'Results come from a predefined Java fixture. This is not an executed static analysis or a remote repository connection.'
                : 'No repository adapter or identity is configured. Submitting will not fetch the URL or imply a successful connection.'}
            </Notice>
            {error && (
              <Notice title="Analysis not completed" tone="error">
                {error}
              </Notice>
            )}
          </div>
          <div className="modal-footer">
            <Button onClick={() => setAnalysisOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={!confirmed || !scope.length}
              busy={busy}
            >
              <FileSearch size={18} />
              Analyse project
            </Button>
          </div>
        </form>
      </Modal>
      <Drawer
        open={Boolean(finding)}
        onClose={() => setFinding(null)}
        title={finding?.title ?? 'Source finding'}
        subtitle={finding?.id}
      >
        {finding && (
          <>
            <div className="detail-badges">
              <Badge>{finding.severity}</Badge>
              <Badge tone="outline">
                Confidence {finding.confidence.toFixed(2)}
              </Badge>
            </div>
            <dl>
              <KeyValue label="Source file" mono>
                {finding.file}
              </KeyValue>
              <KeyValue label="Line">{finding.line}</KeyValue>
              <KeyValue label="Category">{finding.category}</KeyValue>
            </dl>
            <h3 className="detail-section-title">Supporting evidence</h3>
            <EvidenceLinks ids={finding.evidence} />
            <h3 className="detail-section-title">Remediation guidance</h3>
            <p className="body-copy">{finding.guidance}</p>
            <h3 className="detail-section-title">Validation criteria</h3>
            <p className="body-copy">{finding.validation}</p>
            <Button
              onClick={() => {
                setFilePath(finding.file)
                setTab('Source explorer')
                setFinding(null)
              }}
            >
              <FileCode2 size={15} />
              Open source excerpt
            </Button>
          </>
        )}
      </Drawer>
    </div>
  )
}

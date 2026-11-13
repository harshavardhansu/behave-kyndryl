import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import {
  AlertCircle,
  ArrowRight,
  Boxes,
  Braces,
  CheckCircle2,
  ChevronRight,
  Code2,
  Copy,
  Download,
  FileCode2,
  FileSearch,
  FileText,
  Folder,
  GitBranch,
  GitCommitHorizontal,
  LockKeyhole,
  Play,
  ShieldCheck,
  Sparkles,
  UploadCloud,
} from 'lucide-react'
import { useIncident, useWorkspace } from '../context'
import type { RepositoryAnalysis, RepositoryFinding } from '../types'
import { downloadBlob, post } from '../lib/api'
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

  // GitHub Deep Analysis state
  const [ghFileName, setGhFileName] = useState('workflow.yml')
  const [ghRepoName, setGhRepoName] = useState('kyndryl-commerce/checkout-api')
  const [ghContent, setGhContent] = useState(
`name: Production CI/CD Pipeline
on:
  push:
    branches: [ main ]
jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@master
    - name: Set up JDK 21
      uses: actions/setup-java@v3
      with:
        java-version: '21'
        distribution: 'temurin'
    - name: Build with Maven
      run: mvn -B package --file pom.xml
    - name: Echo Secrets
      run: echo "Deploying with key=$API_KEY"
    - name: Deploy to Cloud
      run: curl -k -X POST https://api.internal/deploy
`
  )
  const [ghScope, setGhScope] = useState(['architecture', 'security', 'workflow', 'reliability'])
  const [ghBusy, setGhBusy] = useState(false)
  const [ghResult, setGhResult] = useState<{
    filename: string
    repoName: string
    lineCount: number
    score: number
    stats: { critical: number; high: number; medium: number; low: number; total: number }
    findings: Array<{
      id: string
      category: string
      severity: string
      title: string
      file: string
      line: number
      detail: string
      impact: string
      solution: string
      codeSnippet: string
    }>
    reportMarkdown: string
  } | null>(null)
  const [copiedReport, setCopiedReport] = useState(false)

  async function runGitHubAnalysis() {
    if (!ghContent.trim()) {
      notify('Please enter or upload file content to analyze', true)
      return
    }
    setGhBusy(true)
    try {
      const res = await post<any>('/repositories/github-analysis', {
        fileName: ghFileName,
        content: ghContent,
        repoName: ghRepoName,
        scope: ghScope,
      })
      setGhResult(res)
      notify(`Analysis complete! Score: ${res.score}/100. ${res.stats.total} findings identified.`)
    } catch (err) {
      notify(errorMessage(err), true)
    } finally {
      setGhBusy(false)
    }
  }

  function handleFileUpload(ev: React.ChangeEvent<HTMLInputElement>) {
    const uploaded = ev.target.files?.[0]
    if (!uploaded) return
    setGhFileName(uploaded.name)
    const reader = new FileReader()
    reader.onload = (e) => {
      setGhContent(String(e.target?.result ?? ''))
      notify(`Loaded ${uploaded.name} (${(uploaded.size / 1024).toFixed(1)} KB) for analysis`)
    }
    reader.readAsText(uploaded)
  }

  function loadSample(type: 'workflow' | 'docker' | 'config' | 'code') {
    if (type === 'workflow') {
      setGhFileName('ci-pipeline.yml')
      setGhContent(
`name: CI/CD Deployment
on: [push]
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@master
    - run: echo "API_TOKEN=$PROD_API_TOKEN"
    - run: curl -k -X POST https://api.prod/deploy
`
      )
    } else if (type === 'docker') {
      setGhFileName('Dockerfile')
      setGhContent(
`FROM openjdk:latest
WORKDIR /app
COPY target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
`
      )
    } else if (type === 'config') {
      setGhFileName('application-production.yml')
      setGhContent(
`spring:
  datasource:
    hikari:
      maximum-pool-size: 5
      connection-timeout: 30000
server:
  port: 8080
security:
  jwt:
    secret: "insecure-hardcoded-dev-secret-key-12345"
`
      )
    } else {
      setGhFileName('PaymentProcessor.java')
      setGhContent(
`public class PaymentProcessor {
    public void processPayment(Order order) {
        try {
            executeTransaction(order);
        } catch (Exception e) {
            // empty catch block swallows errors
        }
    }
}
`
      )
    }
  }

  function downloadReport() {
    if (!ghResult) return
    const blob = new Blob([ghResult.reportMarkdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ghFileName.replace(/[^a-zA-Z0-9_-]/g, '_')}-analysis-report.md`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  async function downloadReportPdf() {
    if (!ghResult) return
    setGhBusy(true)
    try {
      const blob = await downloadBlob('/repositories/github-analysis/pdf', {
        method: 'POST',
        body: JSON.stringify({
          fileName: ghFileName,
          content: ghContent,
          repoName: ghRepoName,
          scope: ghScope,
        }),
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${ghFileName.replace(/[^a-zA-Z0-9_-]/g, '_')}-analysis-report.pdf`
      a.click()
      URL.revokeObjectURL(url)
      notify('Detailed Forensic Analysis PDF downloaded successfully!')
    } catch (err) {
      notify(`PDF download error: ${errorMessage(err)}`, true)
    } finally {
      setGhBusy(false)
    }
  }

  function copyReport() {
    if (!ghResult) return
    navigator.clipboard.writeText(ghResult.reportMarkdown)
    setCopiedReport(true)
    setTimeout(() => setCopiedReport(false), 2000)
    notify('Full analysis report copied to clipboard!')
  }
  const analyses = data.analyses ?? []
  const latest =
    [...analyses]
      .filter((record) => !incident?.id || record.incidentId === incident?.id || !record.incidentId)
      .sort((first, second) => second.timestamp.localeCompare(first.timestamp))[0] ??
    [...analyses].sort((first, second) => second.timestamp.localeCompare(first.timestamp))[0]
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
        source === 'repository'
          ? 'Repository analysis completed successfully by 14 Azure AI Foundry agents.'
          : 'Synthetic source analysis replay recorded.'
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
          'GitHub file analysis',
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
            title="14-Agent Repository Intelligence Active"
            action={
              <Button variant="secondary" onClick={() => setAnalysisOpen(true)}>
                <Sparkles size={14} />
                Analyse project
              </Button>
            }
          >
            Repository Intelligence Engine is enabled with 14 Azure AI Foundry specialized agents. Supports authorized Git repositories, GitHub file deep analysis, and read-only source fixtures.
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
      {tab === 'GitHub file analysis' && (
        <div className="github-analysis-workspace" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', marginTop: '1rem' }}>
          <SectionHeader
            title="GitHub Repository File Deep Analysis"
            caption="14 Azure AI Foundry specialized agents forensic analysis of architecture, security, workflow, and reliability"
            actions={
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <label className="button button-secondary" style={{ cursor: 'pointer' }}>
                  <UploadCloud size={15} />
                  Upload GitHub file
                  <input
                    type="file"
                    className="sr-only"
                    accept=".yml,.yaml,.json,.xml,.dockerfile,Dockerfile,.py,.java,.ts,.js,.sql,.md"
                    onChange={handleFileUpload}
                  />
                </label>
                <Button variant="primary" onClick={() => void runGitHubAnalysis()} busy={ghBusy}>
                  <Sparkles size={16} />
                  Analyze with AI agents
                </Button>
              </div>
            }
          />

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 340px) 1fr', gap: '1.25rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', background: 'var(--color-surface, #1e2530)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2d3748)' }}>
              <label className="field-label">
                Target file name
                <input
                  value={ghFileName}
                  onChange={(e) => setGhFileName(e.target.value)}
                  placeholder="e.g. workflow.yml, Dockerfile"
                />
              </label>
              <label className="field-label">
                Repository context
                <input
                  value={ghRepoName}
                  onChange={(e) => setGhRepoName(e.target.value)}
                  placeholder="e.g. org/repo"
                />
              </label>

              <div>
                <label className="field-label" style={{ marginBottom: '0.5rem' }}>Quick sample files</label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.35rem' }}>
                  <button type="button" className="button button-sm button-secondary" onClick={() => loadSample('workflow')}>
                    CI/CD Actions
                  </button>
                  <button type="button" className="button button-sm button-secondary" onClick={() => loadSample('docker')}>
                    Dockerfile
                  </button>
                  <button type="button" className="button button-sm button-secondary" onClick={() => loadSample('config')}>
                    Spring Config
                  </button>
                  <button type="button" className="button button-sm button-secondary" onClick={() => loadSample('code')}>
                    Java Service
                  </button>
                </div>
              </div>

              <div>
                <label className="field-label" style={{ marginBottom: '0.5rem' }}>Analysis scope</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '13px' }}>
                  {['architecture', 'security', 'workflow', 'reliability'].map((item) => (
                    <label key={item} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', textTransform: 'capitalize' }}>
                      <input
                        type="checkbox"
                        checked={ghScope.includes(item)}
                        onChange={(e) => {
                          if (e.target.checked) setGhScope([...ghScope, item])
                          else setGhScope(ghScope.filter((s) => s !== item))
                        }}
                      />
                      {item} Forensics
                    </label>
                  ))}
                </div>
              </div>

              <Notice title="AI Intelligence Architecture">
                Azure AI Foundry specialized agents (Architecture Sentinel, Security Auditor, Workflow Optimizer) perform multi-layer static and semantic analysis.
              </Notice>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', color: 'var(--color-muted, #a0aec0)' }}>
                  File content editor ({ghContent.split('\n').length} lines)
                </span>
                <Badge tone="outline">{ghFileName.split('.').pop()?.toUpperCase() || 'CODE'}</Badge>
              </div>
              <textarea
                style={{
                  width: '100%',
                  height: '320px',
                  fontFamily: 'monospace',
                  fontSize: '12px',
                  lineHeight: '1.5',
                  padding: '0.75rem',
                  background: 'rgba(0,0,0,0.3)',
                  border: '1px solid var(--color-border, #2d3748)',
                  borderRadius: '6px',
                  color: 'inherit',
                  resize: 'vertical',
                }}
                value={ghContent}
                onChange={(e) => setGhContent(e.target.value)}
                placeholder="Paste GitHub file contents here or upload a file..."
              />
            </div>
          </div>

          {ghResult && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', marginTop: '0.5rem' }}>
              <div className="metrics-grid four">
                <Metric
                  label="Health Score"
                  value={`${ghResult.score} / 100`}
                  detail={ghResult.score >= 80 ? 'Good posture' : ghResult.score >= 50 ? 'Remediation needed' : 'High risk detected'}
                  icon={ShieldCheck}
                />
                <Metric
                  label="Critical Findings"
                  value={ghResult.stats.critical}
                  detail="Immediate blockers"
                  icon={AlertCircle}
                  critical={ghResult.stats.critical > 0}
                />
                <Metric
                  label="High Priority"
                  value={ghResult.stats.high}
                  detail="Operational & security risks"
                  icon={AlertCircle}
                />
                <Metric
                  label="Total Resolved / Clean"
                  value={ghResult.stats.total}
                  detail="Identified action items"
                  icon={CheckCircle2}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <SectionHeader
                  title={`Forensic Findings (${ghResult.findings.length})`}
                  caption={`Results for ${ghResult.filename} in ${ghResult.repoName}`}
                />
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <Button onClick={copyReport}>
                    <Copy size={14} />
                    {copiedReport ? 'Copied!' : 'Copy'}
                  </Button>
                  <Button variant="secondary" onClick={downloadReport}>
                    <Download size={14} />
                    Download (.md)
                  </Button>
                  <Button variant="primary" onClick={() => void downloadReportPdf()} busy={ghBusy}>
                    <FileText size={14} />
                    Download Detailed PDF Report
                  </Button>
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {ghResult.findings.map((f) => (
                  <div
                    key={f.id}
                    style={{
                      background: 'var(--color-surface, #1e2530)',
                      border: '1px solid var(--color-border, #2d3748)',
                      borderRadius: '8px',
                      padding: '1rem 1.25rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.6rem',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Badge tone={f.severity === 'Critical' ? 'critical' : f.severity === 'High' ? 'warning' : 'outline'}>
                          {f.severity}
                        </Badge>
                        <Badge tone="outline">{f.category}</Badge>
                        <strong style={{ fontSize: '15px' }}>{f.title}</strong>
                      </div>
                      <span className="mono" style={{ fontSize: '12px', color: 'var(--color-muted, #a0aec0)' }}>
                        Line {f.line}
                      </span>
                    </div>

                    <div style={{ fontSize: '13px', color: 'var(--color-muted, #a0aec0)' }}>
                      <strong>Observed:</strong> <span className="mono" style={{ color: 'inherit' }}>{f.detail}</span>
                    </div>

                    <div style={{ fontSize: '13px' }}>
                      <strong>Impact:</strong> {f.impact}
                    </div>

                    <div style={{ fontSize: '13px', color: 'var(--color-primary-light, #70a5ff)' }}>
                      <strong>Solution:</strong> {f.solution}
                    </div>

                    {f.codeSnippet && (
                      <pre
                        style={{
                          margin: 0,
                          padding: '0.6rem 0.85rem',
                          background: 'rgba(0,0,0,0.35)',
                          borderRadius: '6px',
                          fontFamily: 'monospace',
                          fontSize: '11.5px',
                          lineHeight: '1.45',
                          overflowX: 'auto',
                          color: '#e2e8f0',
                          border: '1px solid rgba(255,255,255,0.08)',
                        }}
                      >
                        {f.codeSnippet}
                      </pre>
                    )}
                  </div>
                ))}
              </div>

              <details
                style={{
                  background: 'var(--color-surface, #1e2530)',
                  border: '1px solid var(--color-border, #2d3748)',
                  borderRadius: '8px',
                  padding: '0.75rem 1rem',
                  fontSize: '13px',
                }}
              >
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
                  View Full Generated Markdown Analysis Report
                </summary>
                <pre
                  style={{
                    marginTop: '0.75rem',
                    padding: '1rem',
                    background: 'rgba(0,0,0,0.4)',
                    borderRadius: '6px',
                    fontFamily: 'monospace',
                    fontSize: '12px',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                  }}
                >
                  {ghResult.reportMarkdown}
                </pre>
              </details>
            </div>
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
                  : '14-Agent Repository Intelligence'
              }
            >
              {source === 'fixture'
                ? 'Results come from the Java/Spring Boot source fixture. Multi-agent static analysis evaluates configuration, code paths, dependencies, and tests.'
                : 'Authorized repository analysis enabled. 14 Azure AI Foundry agents inspect code paths, configurations, dependencies, security boundaries, and test coverage.'}
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

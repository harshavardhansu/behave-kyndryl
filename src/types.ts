export type Environment = 'Production' | 'Staging' | 'Development' | 'Sandbox'
export type Severity = 'Critical' | 'High' | 'Medium' | 'Low'
export type Health = 'Healthy' | 'Degraded' | 'Critical'
export type IncidentStatus =
  | 'New'
  | 'Triaged'
  | 'Investigating'
  | 'Root Cause Identified'
  | 'Fix Proposed'
  | 'Testing'
  | 'Awaiting Approval'
  | 'Approved'
  | 'Deploying'
  | 'Monitoring'
  | 'Resolved'
  | 'Closed'
  | 'Reopened'
export type AgentStatus =
  | 'Idle'
  | 'Queued'
  | 'Running'
  | 'Waiting for Evidence'
  | 'Waiting for Human Approval'
  | 'Completed'
  | 'Failed'
  | 'Cancelled'
  | 'Paused'
export type EvidenceClass = 'Observed' | 'Inferred' | 'Unverified' | 'Validated'

export interface Incident {
  id: string
  title: string
  description: string
  severity: Severity
  status: IncidentStatus
  service: string
  environment: Environment
  detectedAt: string
  owner: string
  commander: string
  impact: string
  source: string
  correlationId: string
  error: string
  expected: string
  actual: string
  steps: string
  slaMinutes: number
  workflowStatus:
  'Idle' | 'Running' | 'Paused' | 'Completed' | 'Cancelled' | 'Failed'
  workflowGeneration: number
  outcome: string
  recovery: null | {
    timestamp: string
    errorRate: number
    latency: number
    actor: string
    synthetic: boolean
    evidence: string
  }
  synthetic: boolean
}

export interface Service {
  id: string
  name: string
  type:
  | 'Web'
  | 'API'
  | 'Service'
  | 'Database'
  | 'Cache'
  | 'Queue'
  | 'Cloud'
  | 'External'
  health: Health
  environment: Environment
  latency: number
  errorRate: number
  rps: number
  observedAt: string
  evidence: string[]
  changes: string[]
  incidents: string[]
  position: { x: number; y: number }
}

export interface Dependency {
  id: string
  source: string
  target: string
  relationship: string
  strength: number
  classification: EvidenceClass
  latency: number
  timestamp: string
  evidence: string[]
  critical: boolean
}

export interface Evidence {
  id: string
  incidentId: string
  title: string
  type: string
  source: string
  timestamp: string
  service: string
  environment: Environment
  classification: EvidenceClass
  excerpt: string
  reason: string
  traceId: string
  fileName?: string
  sha256?: string
  synthetic: boolean
}

export interface Hypothesis {
  id: string
  incidentId: string
  title: string
  status: string
  confidence: number
  supports: string[]
  contradicts: string[]
  missing: string[]
  nextStep: string
  agent: string
  timestamp: string
}

export interface Agent {
  id: string
  role: string
  name: string
  purpose: string
  status: AgentStatus
  task: string
  incidentId: string
  startedAt: string | null
  lastActivity: string | null
  dependencies: string[]
  inputs: string[]
  outputs: string[]
  retries: number
  usage: number | null
  approvalRequired: boolean
  phase: number
  limitations: string
}

export interface TestCase {
  name: string
  status: 'Passed' | 'Failed' | 'Skipped'
  expected: string
  actual: string
  duration: number
  error: string
}

export interface TestRun {
  id: string
  incidentId: string
  suite: string
  category: string
  status: 'Passed' | 'Failed' | 'Running'
  passed: number
  failed: number
  skipped: number
  flaky: number
  duration: number
  coverage: number | null
  commit: string
  environment: Environment
  timestamp: string
  cases: TestCase[]
  synthetic: boolean
  source: string
}

export interface SecurityFinding {
  id: string
  title: string
  category: string
  severity: Severity
  service: string
  status: 'Open' | 'Investigating' | 'Resolved' | 'Accepted risk'
  incidentId: string
  description: string
  reference: string
  file: string
  line: number
  guidance: string
}

export interface Gate {
  name: string
  passed: boolean
  detail: string
  required: boolean
}

export interface Change {
  id: string
  incidentId: string
  title: string
  status: string
  risk: string
  owner: string
  environment: Environment
  branch: string
  commit: string
  files: string[]
  diff: string
  rollback: string
  plan: string[]
  justification: string
  approvalId: string | null
  gates: Gate[]
}

export interface Approval {
  id: string
  changeId: string
  incidentId: string
  title: string
  requestedBy: string
  requestedAt: string
  status: 'Pending' | 'Approved' | 'Rejected'
  reviewedBy: string | null
  decidedAt: string | null
  reason: string
}

export interface LogRecord {
  id: string
  timestamp: string
  level: 'ERROR' | 'WARN' | 'INFO' | 'DEBUG'
  service: string
  environment: Environment
  message: string
  traceId: string
  source: string
  attributes: Record<string, string | number>
  evidenceId: string
}

export interface KnowledgeRecord {
  id: string
  title: string
  type: string
  owner: string
  version: string
  reviewedAt: string
  approved: boolean
  source: string
  services: string[]
  incidents: string[]
  body: string
}

export interface AuditEvent {
  id: string
  timestamp: string
  actor: string
  role: string
  action: string
  resource: string
  previous: string
  next: string
  outcome: string
  correlationId: string
  environment: string
  evidence: string
  synthetic: boolean
}

export interface Deployment {
  id: string
  changeId: string
  service: string
  version: string
  environment: Environment
  timestamp: string
  status: string
}

export interface Integration {
  id: string
  name: string
  category: string
  status: 'Demo source' | 'Not configured' | 'Configured, not verified'
  description: string
  required: string[]
}

export interface Policy {
  minimumPassRate: number
  retentionDays: number
  maxTaskSeconds: number
  maxRetries: number
  requireSeparateApprover: boolean
  blockCriticalFindings: boolean
  productionApprovalRequired: boolean
}

export interface RepositoryFinding {
  id: string
  title: string
  severity: Severity
  category: string
  file: string
  line: number
  confidence: number
  evidence: string[]
  guidance: string
  validation: string
}

export interface RepositoryAnalysis {
  id: string
  incidentId: string
  timestamp: string
  source: string
  branch: string
  commit: string
  stack: string
  scope: string[]
  status: string
  findings: RepositoryFinding[]
  limitations: string
}

export interface Snapshot {
  mode: string
  snapshotAt: string
  workspace: string
  incidents: Incident[]
  services: Service[]
  dependencies: Dependency[]
  evidence: Evidence[]
  hypotheses: Hypothesis[]
  agents: Agent[]
  tests: TestRun[]
  security: SecurityFinding[]
  changes: Change[]
  approvals: Approval[]
  logs: LogRecord[]
  knowledge: KnowledgeRecord[]
  audit: AuditEvent[]
  deployments: Deployment[]
  integrations: Integration[]
  policy: Policy
  analyses?: RepositoryAnalysis[]
  trends: {
    date: string
    critical: number
    high: number
    other: number
    resolved: number
  }[]
}

export interface Session {
  user: {
    id: string
    name: string
    initials: string
    role: string
    permissions: string[]
    environments: Environment[]
  }
  csrf: string
  mode: string
  workspace: string
}

export interface IncidentInput {
  title: string
  description: string
  severity: Severity
  environment: Environment
  service: string
  impact: string
  source: string
  error: string
  steps: string
  expected: string
  actual: string
  correlationId: string
  detectedAt: string
}

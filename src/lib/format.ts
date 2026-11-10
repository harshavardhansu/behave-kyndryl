import type { Incident, IncidentStatus } from '../types'

export const environments = ['Production', 'Staging', 'Development', 'Sandbox'] as const
export const severities = ['Critical', 'High', 'Medium', 'Low'] as const
export const roles = [
  'Incident Manager',
  'SRE / Operator',
  'Developer',
  'QA Engineer',
  'Security Analyst',
  'Change Approver',
  'Administrator',
  'Viewer',
]
export const closedStatuses: IncidentStatus[] = ['Resolved', 'Closed']
export const severityRank = { Critical: 0, High: 1, Medium: 2, Low: 3 }

export function time(value: string | null | undefined) {
  if (!value) return 'Not started'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown time'
    : date.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
}

export function dateTime(value: string | null | undefined) {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown time'
    : date.toLocaleString('en-GB', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
}

export function elapsed(value: string, reference = new Date().toISOString()) {
  const minutes = Math.max(
    0,
    Math.floor(
      (new Date(reference).getTime() - new Date(value).getTime()) / 60_000
    )
  )
  if (minutes < 60) return `${minutes}m`
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
  return `${Math.floor(minutes / 1440)}d ${Math.floor((minutes % 1440) / 60)}h`
}

export function sla(incident: Incident, reference?: string) {
  if (closedStatuses.includes(incident.status))
    return { label: 'Completed', risk: false, remaining: 0 }
  const age = Math.max(
    0,
    (new Date(reference ?? new Date().toISOString()).getTime() -
      new Date(incident.detectedAt).getTime()) /
    60_000
  )
  const remaining = Math.ceil(incident.slaMinutes - age)
  return {
    label: remaining <= 0 ? 'Breached' : `${remaining}m remaining`,
    risk: remaining <= 30,
    remaining,
  }
}

export function initials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] ?? '')
    .join('')
    .toUpperCase()
}

export function number(value: number) {
  return new Intl.NumberFormat('en-US', {
    notation: value > 9999 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(value)
}

export const workflowStages = [
  'Detection',
  'Investigation',
  'Root cause',
  'Proposal',
  'Validation',
  'Approval',
  'Deployment',
  'Recovery',
  'Closure',
]

export function stageIndex(status: IncidentStatus): number {
  const stages: Record<IncidentStatus, number> = {
    New: 0,
    Triaged: 0,
    Investigating: 1,
    'Root Cause Identified': 2,
    'Fix Proposed': 3,
    Testing: 4,
    'Awaiting Approval': 5,
    Approved: 5,
    Deploying: 6,
    Monitoring: 7,
    Resolved: 7,
    Closed: 8,
    Reopened: 0,
  }
  return stages[status]
}

export function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : 'The operation could not be completed. Please retry.'
}

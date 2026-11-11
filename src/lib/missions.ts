import type { Mission } from '../types'

/** Display names for specialist roles (mirrors backend/seed.py). */
export const ROLE_NAMES: Record<string, string> = {
    orchestrator: 'Orchestrator',
    intake: 'Intake & classification',
    logs: 'Log analysis',
    observability: 'Observability correlation',
    repository: 'Repository analysis',
    knowledge: 'Knowledge retrieval',
    'root-cause': 'Root-cause analysis',
    remediation: 'Remediation',
    testing: 'Test engineering',
    security: 'Security analysis',
    validation: 'Validation',
    risk: 'Change risk',
    release: 'Release coordination',
    summary: 'Incident summary',
}

const OPEN = new Set(['Analysing', 'Awaiting team approval', 'Working', 'Awaiting decision', 'Awaiting resolution review', 'Paused'])

export function latestMission(missions: Mission[] | undefined, incidentId: string) {
    return [...(missions ?? [])]
        .filter((mission) => mission.incidentId === incidentId)
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt))[0]
}

export function isOpenMission(mission: Mission | undefined) {
    return Boolean(mission && OPEN.has(mission.status))
}


import type { Agent, AgentStatus, Incident, Mission, MissionStep } from '../types'

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

/** How many specialist roles the mission engine has (13 today), from its published squads. */
export function specialistCount(steps: MissionStep[] | undefined) {
    return steps?.length ? steps.reduce((total, step) => total + step.roles.length, 0) : 13
}

export function isOpenMission(mission: Mission | undefined) {
    return Boolean(mission && OPEN.has(mission.status))
}


/** Fallback when the backend does not publish its squads (workspace `missionSteps`). */
const STEP_ORDER = ['investigate', 'diagnose', 'remediate', 'govern']

export function missionCaption(mission: Mission | undefined) {
    if (!mission) return 'Awaiting ticket analysis'
    return {
        Analysing: `Analysing ticket · iteration ${mission.iteration}`,
        'Awaiting team approval': 'Team proposed · awaiting approval',
        Working: `Team at work · iteration ${mission.iteration}`,
        'Awaiting decision': 'Awaiting human decision',
        'Awaiting resolution review': 'Outcome ready for review',
        Resolved: `Resolved · iteration ${mission.iteration}`,
        'Solution ready': 'Solution approved · handed to the owning team',
        Escalated: 'Escalated to a human',
        Cancelled: 'Mission cancelled',
        Paused: 'Mission paused',
    }[mission.status]
}

/**
 * The agents of an incident's mission, shaped like workflow tasks so every page
 * (War Room, Agent orchestration) shows the same team: the Orchestrator, the
 * approved team of the current iteration (or the proposed team while it waits
 * for approval). Hand-offs follow the mission steps, so each agent depends on
 * the agents of the previous step that has team members.
 */
export function missionTeam(incident: Incident, mission: Mission | undefined, steps?: MissionStep[]) {
    const stepOrder = steps?.length ? steps.map((step) => step.id) : STEP_ORDER
    const iteration = mission?.iterations[mission.iterations.length - 1]
    const caption = missionCaption(mission)
    const orchestratorStatus: AgentStatus = !mission
        ? 'Idle'
        : mission.status === 'Analysing' || mission.status === 'Working'
            ? 'Running'
            : mission.status.startsWith('Awaiting')
                ? 'Waiting for Human Approval'
                : mission.status === 'Resolved' || mission.status === 'Solution ready'
                    ? 'Completed'
                    : mission.status === 'Escalated'
                        ? 'Failed'
                        : mission.status === 'Cancelled'
                            ? 'Cancelled'
                            : 'Paused'
    const limitations = mission
        ? `${mission.mode}. Agents investigate with read-only tools and cannot change anything; humans approve every important step.`
        : 'No mission yet. Start an agent mission to have the Orchestrator form a team.'
    const proposed = iteration && !iteration.team.length && iteration.plan ? iteration.plan.selected : []
    const orchestratorId = `${mission?.id ?? incident.id}-orchestrator`
    const members = (iteration?.team ?? []).map((member) => ({
        id: member.id, role: member.role, step: member.step, member,
    }))
    const stepsWithMembers = stepOrder.filter((step) => members.some((item) => item.step === step))
    const dependenciesOf = (step: string) => {
        const index = stepsWithMembers.indexOf(step)
        if (index <= 0) return [orchestratorId]
        return members.filter((item) => item.step === stepsWithMembers[index - 1]).map((item) => item.id)
    }
    const agents: Agent[] = [
        {
            id: orchestratorId, role: 'orchestrator', name: 'Orchestrator',
            purpose: 'Analyses the ticket, forms the team, coordinates hand-offs and asks humans for every important decision.',
            status: orchestratorStatus, task: iteration?.plan?.analysis ?? caption, incidentId: incident.id,
            startedAt: mission?.createdAt ?? null, lastActivity: mission?.updatedAt ?? null, dependencies: [], inputs: [], outputs: [],
            retries: 0, usage: null, approvalRequired: true, phase: -1, limitations,
        },
        ...members.map(({ member }): Agent => ({
            id: member.id, role: member.role, name: member.name, purpose: `Chosen because: ${member.reason}`,
            status: member.status === 'Not reached' ? 'Cancelled' : member.status, task: member.findings?.summary ?? member.task,
            incidentId: incident.id, startedAt: member.startedAt, lastActivity: member.completedAt ?? member.startedAt,
            dependencies: dependenciesOf(member.step), inputs: member.findings?.evidenceIds ?? [], outputs: [], retries: 0, usage: null,
            approvalRequired: member.role === 'remediation' || member.role === 'root-cause', phase: stepOrder.indexOf(member.step),
            limitations: member.findings?.source ? `${member.findings.source}. Humans approve every important step.` : limitations,
        })),
        ...proposed.map((item): Agent => ({
            id: `${mission?.id}-proposed-${item.role}`, role: item.role, name: ROLE_NAMES[item.role] ?? item.role,
            purpose: `Proposed because: ${item.reason}`, status: 'Waiting for Human Approval', task: 'Proposed by the Orchestrator; waiting for team approval',
            incidentId: incident.id, startedAt: null, lastActivity: null, dependencies: [orchestratorId], inputs: [], outputs: [], retries: 0,
            usage: null, approvalRequired: true, phase: 0, limitations,
        })),
    ]
    const skipped = (iteration?.team.length ? iteration.skipped : iteration?.plan?.skipped ?? []).map((item) => ({
        role: item.role, name: ROLE_NAMES[item.role] ?? item.role, reason: item.reason,
    }))
    return { iteration, caption, agents, proposed, skipped }
}

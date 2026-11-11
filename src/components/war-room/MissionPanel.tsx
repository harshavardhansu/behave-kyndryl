import { useMemo, useState } from 'react'
import {
    Ban,
    Bot,
    CheckCircle2,
    CircleAlert,
    Flag,
    GitBranch,
    Lightbulb,
    Play,
    RotateCcw,
    ShieldCheck,
    Users,
    XCircle,
} from 'lucide-react'
import type { Incident, Mission, MissionGate } from '../../types'
import { isOpenMission, ROLE_NAMES } from '../../lib/missions'
import { post } from '../../lib/api'
import { errorMessage, time } from '../../lib/format'
import { useWorkspace } from '../../context'
import { Badge, Button } from '../ui'
import './mission-panel.css'

const STATUS_TONE: Record<string, 'success' | 'warning' | 'critical' | 'neutral' | 'outline'> = {
    Analysing: 'outline',
    Working: 'outline',
    'Awaiting team approval': 'warning',
    'Awaiting decision': 'warning',
    'Awaiting resolution review': 'warning',
    Resolved: 'success',
    Escalated: 'critical',
    Cancelled: 'neutral',
    Paused: 'neutral',
}

const GATE_ICON = { team: Users, 'root-cause': Lightbulb, fix: ShieldCheck, resolution: Flag }

function TeamEditor({
    mission,
    remove,
    add,
    onToggle,
}: {
    mission: Mission
    remove: Set<string>
    add: Set<string>
    onToggle: (role: string, selected: boolean) => void
}) {
    const plan = mission.iterations[mission.iterations.length - 1]?.plan
    if (!plan) return null
    return (
        <div className="mission-team-editor">
            <div>
                <span className="mission-label">Proposed team ({plan.selected.length - remove.size + add.size})</span>
                <ul>
                    {plan.selected.map((item, index) => (
                        <li key={item.role} className={remove.has(item.role) ? 'is-off' : ''} style={{ animationDelay: `${index * 60}ms` }}>
                            <label>
                                <input type="checkbox" checked={!remove.has(item.role)} onChange={() => onToggle(item.role, true)} />
                                <strong>{ROLE_NAMES[item.role] ?? item.role}</strong>
                            </label>
                            <small>{item.reason}</small>
                        </li>
                    ))}
                </ul>
            </div>
            <div>
                <span className="mission-label">Left out ({plan.skipped.length - add.size})</span>
                <ul>
                    {plan.skipped.map((item, index) => (
                        <li key={item.role} className={add.has(item.role) ? '' : 'is-off'} style={{ animationDelay: `${(plan.selected.length + index) * 60}ms` }}>
                            <label>
                                <input type="checkbox" checked={add.has(item.role)} onChange={() => onToggle(item.role, false)} />
                                <strong>{ROLE_NAMES[item.role] ?? item.role}</strong>
                            </label>
                            <small>{item.reason}</small>
                        </li>
                    ))}
                </ul>
            </div>
        </div>
    )
}

function GateCard({ mission, gate, incident }: { mission: Mission; gate: MissionGate; incident: Incident }) {
    const { can, session, notify, refresh } = useWorkspace()
    const [note, setNote] = useState('')
    const [remove, setRemove] = useState<Set<string>>(new Set())
    const [add, setAdd] = useState<Set<string>>(new Set())
    const [busy, setBusy] = useState('')
    const [error, setError] = useState('')

    const allowed = can(gate.requires, incident.environment)
    const separation = gate.type === 'fix' && session.user.id === mission.requestedById
    const blocked = !allowed || separation
    const Icon = GATE_ICON[gate.type]

    async function send(decision: string) {
        setBusy(decision)
        setError('')
        try {
            await post(`/missions/${mission.id}/decision`, {
                gateId: gate.id,
                decision,
                note,
                addRoles: [...add],
                removeRoles: [...remove],
            })
            await refresh()
            notify(decision === 'approve' ? 'Decision recorded. The team continues.' : 'Decision recorded.')
        } catch (failure) {
            setError(errorMessage(failure))
        } finally {
            setBusy('')
        }
    }

    function toggle(role: string, proposed: boolean) {
        const update = (current: Set<string>) => {
            const next = new Set(current)
            if (next.has(role)) next.delete(role)
            else next.add(role)
            return next
        }
        if (proposed) setRemove(update)
        else setAdd(update)
    }

    const buttons: { decision: string; label: string; variant: 'primary' | 'secondary' | 'danger'; icon: typeof CheckCircle2 }[] =
        gate.type === 'team'
            ? [
                { decision: 'approve', label: 'Approve team', variant: 'primary', icon: CheckCircle2 },
                { decision: 'reject', label: 'Reject & re-plan', variant: 'secondary', icon: XCircle },
            ]
            : gate.type === 'resolution'
                ? [
                    { decision: 'resolve', label: 'Confirm resolved', variant: gate.recommendation.startsWith('Confirm') ? 'primary' : 'secondary', icon: CheckCircle2 },
                    { decision: 'iterate', label: 'Start another iteration', variant: gate.recommendation.startsWith('Start') ? 'primary' : 'secondary', icon: RotateCcw },
                    { decision: 'escalate', label: 'Escalate', variant: gate.recommendation.startsWith('Escalate') ? 'primary' : 'secondary', icon: CircleAlert },
                ]
                : [
                    { decision: 'approve', label: gate.type === 'fix' ? 'Approve fix' : 'Approve root cause', variant: 'primary', icon: CheckCircle2 },
                    { decision: 'reject', label: 'Reject, investigate further', variant: 'secondary', icon: XCircle },
                ]

    return (
        <section className={`mission-gate gate-${gate.type}`} aria-label={`Human decision: ${gate.title}`}>
            <div className="mission-gate-head">
                <span className="mission-gate-icon"><Icon size={18} /></span>
                <div>
                    <span className="mission-gate-kicker">Human decision required · iteration {gate.iteration}</span>
                    <h4>{gate.title}</h4>
                </div>
            </div>
            <p className="mission-gate-detail">{gate.detail}</p>
            <p className="mission-gate-recommendation"><Bot size={13} /> Orchestrator recommends: {gate.recommendation}</p>
            {gate.type === 'team' && <TeamEditor mission={mission} remove={remove} add={add} onToggle={toggle} />}
            <label className="mission-note">
                <span>{gate.type === 'team' || gate.type === 'resolution' ? 'Note (optional; required to reject)' : 'Reason (required to reject)'}</span>
                <input value={note} maxLength={600} onChange={(event) => setNote(event.target.value)} placeholder="Add context for the audit trail and the next iteration" />
            </label>
            {blocked && (
                <p className="mission-gate-blocked">
                    {separation
                        ? 'Separation of duties: you started this mission, so a different person must approve the fix. Switch to the Change Approver persona from the profile menu.'
                        : `Your ${session.user.role} role cannot make this decision.`}
                </p>
            )}
            {error && <p className="mission-gate-error">{error}</p>}
            <div className="mission-gate-actions">
                {buttons.map(({ decision, label, variant, icon: ButtonIcon }) => (
                    <Button key={decision} variant={variant} disabled={blocked || Boolean(busy)} busy={busy === decision} onClick={() => void send(decision)}>
                        <ButtonIcon size={15} /> {label}
                    </Button>
                ))}
            </div>
        </section>
    )
}

function tokens(value: number) {
    return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}

function AIUsageMeter() {
    const { data } = useWorkspace()
    const usage = data.aiUsage
    const ai = data.aiMode?.startsWith('AI-GENERATED')
    if (!ai) return <span className="mission-usage is-off" title="No AI provider configured; missions use the free simulated planner.">Planner: simulated (free)</span>
    const calls = usage?.calls ?? 0
    const limit = usage?.limit ?? 0
    const ratio = limit ? Math.min(calls / limit, 1) : 0
    return (
        <span className={`mission-usage ${ratio >= 0.8 ? 'is-high' : ''}`} title={`AI usage today (UTC). Cached answers reused: ${usage?.cacheHits ?? 0}. All time: ${usage?.totals.calls ?? 0} calls.`}>
            <Bot size={12} /> {data.aiMode?.split(' / ')[1] ?? 'AI'} · {calls}/{limit} calls today · {tokens((usage?.inputTokens ?? 0) + (usage?.outputTokens ?? 0))} tokens
            <i style={{ width: `${ratio * 100}%` }} />
        </span>
    )
}

export function MissionPanel({ incident, mission }: { incident: Incident; mission: Mission | undefined }) {
    const { can, notify, refresh } = useWorkspace()
    const [busy, setBusy] = useState(false)
    const events = useMemo(() => [...(mission?.events ?? [])].reverse().slice(0, 14), [mission?.events])
    const open = isOpenMission(mission)

    async function call(path: string, message: string) {
        setBusy(true)
        try {
            await post(path, {})
            await refresh()
            notify(message)
        } catch (failure) {
            notify(errorMessage(failure), true)
        } finally {
            setBusy(false)
        }
    }

    if (!mission || !open) {
        return (
            <section className="mission-panel mission-empty">
                <div className="mission-empty-copy">
                    <span className="mission-empty-icon"><Bot size={20} /></span>
                    <div>
                        <h4>{mission ? `Last mission ${mission.status.toLowerCase()}` : 'No agent mission yet'}</h4>
                        <p>
                            {mission
                                ? `${mission.id} ended after ${mission.iteration} iteration(s). Start a new mission to have the Orchestrator analyse the ticket again.`
                                : 'Start a mission: the Orchestrator analyses this ticket, proposes a team of only the specialists it needs, and waits for your approval at every important step.'}
                        </p>
                    </div>
                </div>
                <div className="mission-empty-actions">
                    <AIUsageMeter />
                    <Button variant="primary" disabled={busy || !can('workflow:run', incident.environment)} busy={busy} onClick={() => void call(`/incidents/${incident.id}/missions`, 'Mission started. The Orchestrator is analysing the ticket.')}>
                        <Play size={15} /> Start agent mission
                    </Button>
                </div>
            </section>
        )
    }

    const current = mission.iterations[mission.iterations.length - 1]
    const running = mission.status === 'Analysing' || mission.status === 'Working'

    return (
        <section className="mission-panel" aria-label="Agent mission">
            <div className="mission-head">
                <div className="mission-title">
                    <Bot size={16} />
                    <strong>Agent mission</strong>
                    <span className="mono">{mission.id}</span>
                    <Badge tone="outline" dot={false}>{mission.mode.split(' / ')[0]}</Badge>
                    <Badge tone={STATUS_TONE[mission.status]}>{mission.status}</Badge>
                    {running && <span className="mission-live"><i /> live</span>}
                </div>
                <div className="mission-iterations" aria-label={`Iteration ${mission.iteration} of ${mission.maxIterations}`}>
                    {Array.from({ length: mission.maxIterations }, (_, index) => index + 1).map((number) => {
                        const iteration = mission.iterations.find((item) => item.number === number)
                        const state = number < mission.iteration ? 'done' : number === mission.iteration ? 'current' : 'next'
                        return (
                            <span key={number} className={`mission-iteration is-${state}`} title={iteration?.outcome?.detail ?? ''}>
                                <GitBranch size={12} /> Iteration {number}
                            </span>
                        )
                    })}
                </div>
                <div className="mission-controls">
                    <AIUsageMeter />
                    {mission.status === 'Paused' && (
                        <Button disabled={busy} onClick={() => void call(`/missions/${mission.id}/resume`, 'Mission resumed.')}><Play size={14} /> Resume</Button>
                    )}
                    <Button variant="ghost" disabled={busy || !can('workflow:run', incident.environment)} onClick={() => void call(`/missions/${mission.id}/cancel`, 'Mission cancelled.')}><Ban size={14} /> Cancel mission</Button>
                </div>
            </div>

            {current?.plan && (
                <p className="mission-analysis">
                    <Bot size={13} /> {current.plan.analysis}
                    {current.plan.source && (
                        <span className={`mission-source ${current.plan.source.startsWith('AI') ? 'is-ai' : 'is-fallback'}`} title={current.plan.source}>
                            {current.plan.source.startsWith('AI') ? 'AI-generated plan' : 'Simulated fallback'}
                        </span>
                    )}
                </p>
            )}

            <div className="mission-body">
                <div className="mission-main">
                    {mission.pendingGate ? (
                        <GateCard key={mission.pendingGate.id} mission={mission} gate={mission.pendingGate} incident={incident} />
                    ) : (
                        <div className="mission-working">
                            <span className="mission-spinner" />
                            <div>
                                <strong>{mission.status === 'Analysing' ? 'The Orchestrator is analysing the ticket…' : mission.status === 'Paused' ? 'Mission paused' : 'The team is working…'}</strong>
                                <small>Every step appears in the activity feed and the command view below. You will be asked before any important decision.</small>
                            </div>
                        </div>
                    )}
                    {mission.learnings.length > 0 && (
                        <div className="mission-learnings">
                            <span className="mission-label"><Lightbulb size={13} /> Learned so far</span>
                            <ul>
                                {mission.learnings.map((learning, index) => <li key={index}>{learning}</li>)}
                            </ul>
                        </div>
                    )}
                </div>
                <div className="mission-feed" aria-label="Mission activity">
                    <span className="mission-label">Activity</span>
                    <ol>
                        {events.map((event) => (
                            <li key={event.id} className={`event-${event.type}`}>
                                <time>{time(event.timestamp)}</time>
                                <div>
                                    <strong>{event.actor}</strong>
                                    <span>{event.message}</span>
                                </div>
                            </li>
                        ))}
                    </ol>
                </div>
            </div>
        </section>
    )
}

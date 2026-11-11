import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
    Activity,
    ArrowDown,
    Bot,
    CircleCheck,
    CircleDashed,
    CircleX,
    FileText,
    FlaskConical,
    Flag,
    GitCommitHorizontal,
    HeartPulse,
    LayoutDashboard,
    Lightbulb,
    Lock,
    LockOpen,
    Maximize,
    Microscope,
    Radar,
    Rocket,
    RotateCcw,
    ScrollText,
    Search,
    ShieldCheck,
    Users,
    Waypoints,
    Wrench,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Agent, AgentStatus, Approval, Change, Evidence, Hypothesis, Incident } from '../../types'
import { stageIndex, workflowStages } from '../../lib/format'
import { EmptyState } from '../ui'
import './agent-command.css'

/* ------------------------------------------------------------------ */
/* Model                                                               */
/* ------------------------------------------------------------------ */

type SquadId = 'investigate' | 'diagnose' | 'remediate' | 'govern'
type Corner = 'tl' | 'tr' | 'br' | 'bl'
type SquadState = 'upcoming' | 'active' | 'done'

interface SquadDefinition {
    id: SquadId
    name: string
    caption: string
    roles: string[]
    stages: number[]
    color: string
    icon: LucideIcon
    corner: Corner
}

/** Specialists grouped by the incident lifecycle, read clockwise from the top left. */
const SQUADS: SquadDefinition[] = [
    { id: 'investigate', name: 'Investigate', caption: 'Detection & evidence', roles: ['intake', 'logs', 'observability', 'repository'], stages: [0, 1], color: '#1192E8', icon: Radar, corner: 'tl' },
    { id: 'diagnose', name: 'Diagnose', caption: 'Knowledge & root cause', roles: ['knowledge', 'root-cause'], stages: [2], color: '#8A3FFC', icon: Microscope, corner: 'tr' },
    { id: 'remediate', name: 'Remediate & Validate', caption: 'Fix, tests & quality gates', roles: ['remediation', 'testing', 'security', 'validation'], stages: [3, 4], color: '#D2A106', icon: Wrench, corner: 'br' },
    { id: 'govern', name: 'Govern & Release', caption: 'Risk, approval & recovery', roles: ['risk', 'release', 'summary'], stages: [5, 6, 7, 8], color: '#24A148', icon: Rocket, corner: 'bl' },
]

const HUB_COLOR = '#FF462D'

const STATUS_OPTIONS: AgentStatus[] = [
    'Idle',
    'Queued',
    'Running',
    'Waiting for Evidence',
    'Waiting for Human Approval',
    'Completed',
    'Failed',
    'Cancelled',
    'Paused',
]

function statusColor(status: AgentStatus) {
    if (status === 'Running') return '#29707A'
    if (status === 'Completed') return '#24A148'
    if (status === 'Failed') return '#DA1E28'
    if (status === 'Queued' || status === 'Waiting for Human Approval' || status === 'Waiting for Evidence') return '#D2A106'
    return '#A8A8A8'
}

/** Statuses that get a live "pulse" animation on their dot. */
function isLive(status: AgentStatus) {
    return status === 'Running' || status === 'Queued' || status === 'Waiting for Evidence' || status === 'Waiting for Human Approval'
}

type FanTone = 'good' | 'warn' | 'bad' | 'neutral' | 'info'

interface FanItem {
    key: string
    label: string
    detail: string
    icon: LucideIcon
    tone: FanTone
    evidenceId?: string
}

const TONE_COLOR: Record<FanTone, string> = {
    good: '#24A148',
    warn: '#D2A106',
    bad: '#DA1E28',
    info: '#1192E8',
    neutral: '#8D8D8D',
}

function evidenceIcon(type: string): LucideIcon {
    const value = type.toLowerCase()
    if (value.includes('log')) return ScrollText
    if (value.includes('metric')) return Activity
    if (value.includes('trace')) return Waypoints
    if (value.includes('test')) return FlaskConical
    if (value.includes('change') || value.includes('deploy') || value.includes('diff')) return GitCommitHorizontal
    return FileText
}

function evidenceTone(record: Evidence): FanTone {
    if (record.classification === 'Observed' || record.classification === 'Validated') return 'good'
    if (record.classification === 'Inferred') return 'info'
    return 'neutral'
}

function buildFans({
    incident,
    agents,
    evidence,
    hypotheses,
    change,
    approval,
}: {
    incident: Incident
    agents: Agent[]
    evidence: Evidence[]
    hypotheses: Hypothesis[]
    change?: Change
    approval?: Approval
}): Record<SquadId, FanItem[]> {
    const stage = stageIndex(incident.status)
    const investigateRoles = new Set(SQUADS[0].roles)
    const linkedIds = new Set(agents.filter((agent) => investigateRoles.has(agent.role)).flatMap((agent) => [...agent.inputs, ...agent.outputs]))
    const linked = evidence.filter((record) => linkedIds.has(record.id))
    const investigate = (linked.length ? linked : evidence).slice(0, 5).map((record) => ({
        key: record.id,
        label: record.id,
        detail: `${record.title} · ${record.type} · ${record.classification}`,
        icon: evidenceIcon(record.type),
        tone: evidenceTone(record),
        evidenceId: record.id,
    }))

    const diagnose = [...hypotheses]
        .sort((left, right) => right.confidence - left.confidence)
        .slice(0, 4)
        .map((hypothesis) => ({
            key: hypothesis.id,
            label: `${Math.round(hypothesis.confidence * 100)}%`,
            detail: `${hypothesis.title} · ${hypothesis.status} · confidence ${hypothesis.confidence.toFixed(2)}`,
            icon: Lightbulb,
            tone: (hypothesis.confidence >= 0.6 ? 'good' : hypothesis.confidence >= 0.3 ? 'warn' : 'neutral') as FanTone,
        }))

    const remediate = (change?.gates ?? []).slice(0, 5).map((gate) => ({
        key: gate.name,
        label: gate.name,
        detail: `${gate.name} · ${gate.passed ? 'passed' : 'not passed'} · ${gate.detail}`,
        icon: gate.passed ? CircleCheck : CircleX,
        tone: (gate.passed ? 'good' : 'bad') as FanTone,
    }))

    const approvalTone: FanTone = approval?.status === 'Approved' ? 'good' : approval?.status === 'Rejected' ? 'bad' : approval ? 'warn' : 'neutral'
    const govern: FanItem[] = [
        { key: 'approval', label: 'Human approval', detail: approval ? `Human approval · ${approval.status}${approval.reviewedBy ? ` by ${approval.reviewedBy}` : ''}` : 'Human approval · not requested', icon: ShieldCheck, tone: approvalTone },
        { key: 'deploy', label: 'Deployment', detail: `Deployment · ${stage >= 6 ? 'recorded' : 'not started'}`, icon: Rocket, tone: stage >= 6 ? 'good' : 'neutral' },
        { key: 'recovery', label: 'Recovery', detail: `Recovery verification · ${incident.recovery ? 'recorded' : 'not recorded'}`, icon: HeartPulse, tone: incident.recovery ? 'good' : 'neutral' },
        { key: 'closure', label: 'Closure', detail: `Closure · ${incident.status === 'Closed' ? 'closed' : 'open'}`, icon: Flag, tone: incident.status === 'Closed' ? 'good' : 'neutral' },
    ]

    return { investigate, diagnose, remediate, govern }
}

function squadState(squad: SquadDefinition, stage: number, members: Agent[]): SquadState {
    if (members.some((agent) => agent.status === 'Running')) return 'active'
    if (stage > squad.stages[squad.stages.length - 1]) return 'done'
    if (squad.stages.includes(stage)) return 'active'
    return 'upcoming'
}

function hubCaption(incident: Incident) {
    const stage = workflowStages[stageIndex(incident.status)] ?? 'Detection'
    if (incident.workflowStatus === 'Running') return `Orchestrating · ${stage}`
    if (incident.workflowStatus === 'Completed') return 'Workflow completed'
    if (incident.workflowStatus === 'Idle') return stageIndex(incident.status) <= 1 ? 'Awaiting input' : `Idle · ${stage}`
    return `${incident.workflowStatus} · ${stage}`
}

/* ------------------------------------------------------------------ */
/* Geometry                                                            */
/* ------------------------------------------------------------------ */

interface Point { x: number; y: number }

interface SquadLayout {
    hex: Point
    side: -1 | 1
    card: { left: number; width: number; top: number }
    fanX: number
    fanYs: number[]
    hubPath: string
    cardPath: string
    fanPaths: string[]
    gate?: Point
}

const COMPACT_BREAKPOINT = 900

function bezierPoint(p0: Point, p1: Point, p2: Point, p3: Point, t: number): Point {
    const u = 1 - t
    return {
        x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
        y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
    }
}

function computeLayout(width: number, height: number, fanCounts: Record<SquadId, number>) {
    const hub: Point = { x: width / 2, y: height * 0.48 }
    const cardWidth = Math.max(196, Math.min(250, width * 0.19))
    const layouts = {} as Record<SquadId, SquadLayout>
    SQUADS.forEach((squad) => {
        const side: -1 | 1 = squad.corner === 'tl' || squad.corner === 'bl' ? -1 : 1
        const top = squad.corner === 'tl' || squad.corner === 'tr'
        const hex: Point = { x: width / 2 + side * width * 0.165, y: height * (top ? 0.25 : 0.74) }
        const cardInner = hex.x + side * 64
        const cardLeft = side === -1 ? cardInner - cardWidth : cardInner
        const cardOuter = side === -1 ? cardLeft : cardLeft + cardWidth
        const fanX = cardOuter + side * 44
        const count = fanCounts[squad.id]
        const spacing = 34
        const fanYs = Array.from({ length: count }, (_, index) => hex.y + (index - (count - 1) / 2) * spacing)
        const port: Point = { x: hex.x - side * 42, y: hex.y }
        const c1: Point = { x: hub.x, y: (hub.y + port.y) / 2 }
        const c2: Point = { x: (hub.x + port.x) / 2, y: port.y }
        const hubPath = `M ${hub.x} ${hub.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${port.x} ${port.y}`
        const cardPath = `M ${hex.x + side * 40} ${hex.y} L ${cardInner} ${hex.y}`
        const fanPaths = fanYs.map((y) => {
            const startX = fanX - side * 14
            const midX = (startX + cardOuter) / 2
            return `M ${startX} ${y} C ${midX} ${y}, ${midX} ${hex.y}, ${cardOuter} ${hex.y}`
        })
        layouts[squad.id] = {
            hex,
            side,
            card: { left: cardLeft, width: cardWidth, top: hex.y },
            fanX,
            fanYs,
            hubPath,
            cardPath,
            fanPaths,
            gate: squad.id === 'govern' ? bezierPoint(hub, c1, c2, port, 0.55) : undefined,
        }
    })
    return { hub, layouts }
}

/* ------------------------------------------------------------------ */
/* Pieces                                                              */
/* ------------------------------------------------------------------ */

/** Extruded hexagon badge with a glyph; reads as a small 3D tile. */
function HexBadge({ color, icon: Icon, size, dim = false }: { color: string; icon: LucideIcon; size: number; dim?: boolean }) {
    const id = `hex-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
    const points = '50,4 90,27 90,73 50,96 10,73 10,27'
    const inner = '50,14 81,32 81,68 50,86 19,68 19,32'
    return (
        <span className={`cmd-hex ${dim ? 'is-dim' : ''}`} style={{ '--node-color': color, width: size, height: size } as CSSProperties}>
            <svg className="cmd-hex-shape" viewBox="0 0 100 108" aria-hidden="true">
                <defs>
                    <linearGradient id={`${id}-face`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={color} stopOpacity="0.95" />
                        <stop offset="100%" stopColor={color} stopOpacity="0.55" />
                    </linearGradient>
                </defs>
                <polygon points={points} transform="translate(0 8)" fill={color} opacity="0.22" />
                <polygon points={points} fill="#FFFFFF" stroke={color} strokeWidth="3" />
                <polygon points={inner} fill={`url(#${id}-face)`} />
                <polygon points="50,14 81,32 50,50 19,32" fill="#FFFFFF" opacity="0.16" />
            </svg>
            <Icon className="cmd-hex-glyph" size={size * 0.34} strokeWidth={2.2} />
        </span>
    )
}

function FanNode({ item, color, style, onSelectEvidence, matched }: { item: FanItem; color: string; style: CSSProperties; onSelectEvidence: (id: string) => void; matched: boolean }) {
    const Icon = item.icon
    const toneColor = TONE_COLOR[item.tone]
    const content = (
        <>
            <Icon size={14} strokeWidth={2.2} />
            <span className="cmd-fan-tip" role="tooltip">{item.detail}</span>
        </>
    )
    const className = `cmd-fan tone-${item.tone} ${matched ? '' : 'is-dim'}`
    const fanStyle = { ...style, '--fan-color': toneColor, '--squad-color': color } as CSSProperties
    if (item.evidenceId) {
        return (
            <button type="button" className={className} style={fanStyle} aria-label={item.detail} onClick={() => onSelectEvidence(item.evidenceId!)}>
                {content}
            </button>
        )
    }
    return (
        <span className={className} style={fanStyle} aria-label={item.detail} tabIndex={0}>
            {content}
        </span>
    )
}

function SquadCard({
    squad,
    members,
    state,
    selectedId,
    isMatch,
    onSelect,
    footer,
}: {
    squad: SquadDefinition
    members: Agent[]
    state: SquadState
    selectedId: string | null
    isMatch: (agent: Agent) => boolean
    onSelect: (agent: Agent) => void
    footer?: ReactNode
}) {
    const completed = members.filter((agent) => agent.status === 'Completed').length
    const progress = members.length ? Math.round((completed / members.length) * 100) : 0
    return (
        <div className={`cmd-card is-${state}`} style={{ '--squad-color': squad.color } as CSSProperties}>
            <div className="cmd-card-head">
                <strong>{squad.name}</strong>
                <span className={`cmd-state is-${state}`}>{state === 'done' ? 'Done' : state === 'active' ? 'Active' : 'Upcoming'}</span>
            </div>
            <small className="cmd-card-caption">{squad.caption}</small>
            <ul className="cmd-members">
                {members.map((agent) => (
                    <li key={agent.id}>
                        <button
                            type="button"
                            className={`cmd-member ${selectedId === agent.id ? 'is-selected' : ''} ${isMatch(agent) ? '' : 'is-dim'} ${isLive(agent.status) ? 'is-live' : ''}`}
                            style={{ '--status-color': statusColor(agent.status) } as CSSProperties}
                            title={`${agent.name} / ${agent.status}`}
                            onClick={() => onSelect(agent)}
                        >
                            <span className="cmd-member-dot" />
                            <span className="cmd-member-name">{agent.name}</span>
                            <span className="cmd-member-status">{agent.status}</span>
                        </button>
                    </li>
                ))}
            </ul>
            <div className="cmd-progress" aria-label={`${completed} of ${members.length} tasks completed`}>
                <span style={{ width: `${progress}%` }} />
            </div>
            <div className="cmd-card-foot">
                <span>{completed}/{members.length} completed</span>
                {footer}
            </div>
        </div>
    )
}

function WorkforceList({ agents, selectedId, onSelect }: { agents: Agent[]; selectedId: string | null; onSelect: (agent: Agent) => void }) {
    const orchestrator = agents.find((agent) => agent.role === 'orchestrator')
    const specialists = agents.filter((agent) => agent.role !== 'orchestrator')
    return (
        <div className="workforce-list" aria-label="Accessible agent workforce">
            {orchestrator && (
                <button className={`workforce-list-agent orchestrator ${selectedId === orchestrator.id ? 'selected' : ''}`} style={{ '--status-color': statusColor(orchestrator.status) } as CSSProperties} onClick={() => onSelect(orchestrator)}>
                    <span className="workforce-list-glyph">O</span>
                    <span><strong>{orchestrator.name}</strong><small>{orchestrator.purpose}</small></span>
                    <b>{orchestrator.status}</b>
                </button>
            )}
            <div className="workforce-list-grid">
                {specialists.map((agent) => (
                    <button key={agent.id} className={`workforce-list-agent ${selectedId === agent.id ? 'selected' : ''}`} style={{ '--status-color': statusColor(agent.status) } as CSSProperties} onClick={() => onSelect(agent)}>
                        <span className="workforce-list-glyph">{agent.name.slice(0, 1)}</span>
                        <span><strong>{agent.name}</strong><small>{agent.purpose}</small></span>
                        <b>{agent.status}</b>
                    </button>
                ))}
            </div>
        </div>
    )
}

/* ------------------------------------------------------------------ */
/* Main view                                                           */
/* ------------------------------------------------------------------ */

export function AgentCommandView({
    incident,
    agents,
    evidence,
    hypotheses,
    change,
    approval,
    selectedId,
    onSelect,
    onSelectEvidence,
    onShowDetails,
}: {
    incident: Incident
    agents: Agent[]
    evidence: Evidence[]
    hypotheses: Hypothesis[]
    change?: Change
    approval?: Approval
    selectedId: string | null
    onSelect: (agent: Agent) => void
    onSelectEvidence: (evidenceId: string) => void
    onShowDetails?: () => void
}) {
    const [view, setView] = useState<'command' | 'list'>('command')
    const [statusFilter, setStatusFilter] = useState('All statuses')
    const [query, setQuery] = useState('')
    const [introKey, setIntroKey] = useState(0)
    const [fullscreen, setFullscreen] = useState(false)
    const [size, setSize] = useState({ width: 0, height: 0 })
    const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    const shell = useRef<HTMLDivElement>(null)
    const stage = useRef<HTMLDivElement>(null)

    useLayoutEffect(() => {
        const element = stage.current
        if (!element) return
        const update = () => setSize({ width: element.clientWidth, height: element.clientHeight })
        update()
        const observer = new ResizeObserver(update)
        observer.observe(element)
        return () => observer.disconnect()
    }, [view, introKey])

    useEffect(() => {
        const query = window.matchMedia('(prefers-reduced-motion: reduce)')
        const update = () => setReducedMotion(query.matches)
        query.addEventListener('change', update)
        return () => query.removeEventListener('change', update)
    }, [])

    useEffect(() => {
        const updateFullscreen = () => setFullscreen(document.fullscreenElement === shell.current)
        document.addEventListener('fullscreenchange', updateFullscreen)
        return () => document.removeEventListener('fullscreenchange', updateFullscreen)
    }, [])

    const orchestrator = agents.find((agent) => agent.role === 'orchestrator')
    const selected = agents.find((agent) => agent.id === selectedId)
    const currentStage = stageIndex(incident.status)
    const membersBySquad = useMemo(() => {
        const result = {} as Record<SquadId, Agent[]>
        SQUADS.forEach((squad) => {
            result[squad.id] = squad.roles.flatMap((role) => agents.filter((agent) => agent.role === role))
        })
        return result
    }, [agents])
    const fans = useMemo(() => buildFans({ incident, agents, evidence, hypotheses, change, approval }), [incident, agents, evidence, hypotheses, change, approval])
    const fanCounts = { investigate: fans.investigate.length, diagnose: fans.diagnose.length, remediate: fans.remediate.length, govern: fans.govern.length }
    const compact = size.width > 0 && size.width < COMPACT_BREAKPOINT
    const geometry = size.width && !compact ? computeLayout(size.width, size.height, fanCounts) : null

    const normalizedQuery = query.trim().toLowerCase()
    const isMatch = (agent: Agent) =>
        (statusFilter === 'All statuses' || agent.status === statusFilter) &&
        (!normalizedQuery || agent.name.toLowerCase().includes(normalizedQuery) || agent.role.toLowerCase().includes(normalizedQuery))
    const fanMatches = (item: FanItem) => !normalizedQuery || item.label.toLowerCase().includes(normalizedQuery) || item.detail.toLowerCase().includes(normalizedQuery)

    const approvalLocked = approval?.status !== 'Approved'
    const runningCount = agents.filter((agent) => agent.status === 'Running').length
    const completedCount = agents.filter((agent) => agent.status === 'Completed').length
    const failedCount = agents.filter((agent) => agent.status === 'Failed').length

    async function toggleFullscreen() {
        if (!shell.current) return
        try {
            if (document.fullscreenElement) await document.exitFullscreen()
            else await shell.current.requestFullscreen()
        } catch {
            setFullscreen(false)
        }
    }

    function submitSearch() {
        const match = agents.find((agent) => agent.role !== 'orchestrator' && isMatch(agent))
        if (match && normalizedQuery) onSelect(match)
    }

    if (!agents.length) {
        return (
            <div className="workforce-empty">
                <EmptyState title="No agent tasks recorded" description="The backend has not created specialist task records for this incident yet. Start an investigation to see its recorded workforce." />
            </div>
        )
    }

    const hubNode = orchestrator && (
        <button
            type="button"
            className={`cmd-hub ${selectedId === orchestrator.id ? 'is-selected' : ''} ${incident.workflowStatus === 'Running' ? 'is-running' : ''}`}
            onClick={() => onSelect(orchestrator)}
            aria-label={`Orchestrator: ${orchestrator.status}. ${hubCaption(incident)}`}
        >
            <span className="cmd-hub-visual">
                <span className="cmd-hub-ripple" />
                <span className="cmd-hub-ripple second" />
                <span className="cmd-hub-orbit" />
                <HexBadge color={HUB_COLOR} icon={Bot} size={compact ? 72 : 96} />
            </span>
            <span className="workforce-core-label">
                <span>ORCHESTRATOR</span>
                <strong>{hubCaption(incident)}</strong>
            </span>
        </button>
    )

    const squadNode = (squad: SquadDefinition, state: SquadState, sizePx: number) => {
        const members = membersBySquad[squad.id]
        const done = members.filter((agent) => agent.status === 'Completed').length
        const anyMatch = members.some(isMatch)
        const holdsSelection = members.some((agent) => agent.id === selectedId)
        return (
            <div className={`cmd-squad is-${state} ${holdsSelection ? 'is-selected' : ''}`} style={{ '--squad-color': squad.color, '--hex': `${sizePx}px`, '--float-delay': `${SQUADS.indexOf(squad) * -0.8}s` } as CSSProperties}>
                <span className="cmd-port left" />
                <HexBadge color={squad.color} icon={squad.icon} size={sizePx} dim={!anyMatch} />
                <span className="cmd-port right" />
                <span className="cmd-squad-pill">{squad.name}<b>{done}/{members.length}</b></span>
            </div>
        )
    }

    return (
        <div className={`cmd-shell ${fullscreen ? 'is-fullscreen' : ''}`} ref={shell}>
            <div className="cmd-toolbar">
                <div className="workforce-mode-switch cmd-switch" role="group" aria-label="Workforce view">
                    <button aria-pressed={view === 'command'} onClick={() => setView('command')}><LayoutDashboard size={14} /> Command view</button>
                    <button aria-pressed={view === 'list'} onClick={() => setView('list')}><Users size={14} /> 2D list</button>
                </div>
                <label className="cmd-filter">Status
                    <select aria-label="Filter workforce by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                        <option>All statuses</option>
                        {STATUS_OPTIONS.map((status) => <option key={status}>{status}</option>)}
                    </select>
                </label>
                <span className="cmd-toolbar-spacer" />
                <button className="cmd-tool" disabled={view !== 'command'} onClick={() => setIntroKey((value) => value + 1)}><RotateCcw size={14} /> Replay intro</button>
                <button className="cmd-tool" aria-label={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'} onClick={() => void toggleFullscreen()}><Maximize size={14} /> Fullscreen</button>
            </div>

            {view === 'list' ? (
                <div className="cmd-list-stage">
                    <WorkforceList agents={agents.filter(isMatch).length ? agents.filter(isMatch) : agents} selectedId={selectedId} onSelect={onSelect} />
                </div>
            ) : (
                <div className={`cmd-stage ${compact ? 'is-compact' : ''}`} ref={stage} key={introKey}>
                    {geometry && (
                        <>
                            <svg className="cmd-links" width={size.width} height={size.height} aria-hidden="true">
                                {SQUADS.map((squad) => {
                                    const layout = geometry.layouts[squad.id]
                                    const state = squadState(squad, currentStage, membersBySquad[squad.id])
                                    const flowing = state === 'active' || (squad.id !== 'govern' && incident.workflowStatus === 'Running' && state !== 'done')
                                    const selectedHere = membersBySquad[squad.id].some((agent) => agent.id === selectedId)
                                    const order = SQUADS.indexOf(squad)
                                    const packetDuration = flowing ? 1.8 : state === 'done' ? 3.6 : 5.2
                                    return (
                                        <g key={squad.id} className={`cmd-link-group is-${state} ${selectedHere ? 'is-selected' : ''}`} style={{ '--squad-color': squad.color, '--delay': `${0.9 + order * 0.12}s` } as CSSProperties}>
                                            <path className="cmd-link-draw" d={layout.hubPath} pathLength={1} />
                                            <path className={`cmd-link hub ${flowing ? 'is-flowing' : ''}`} d={layout.hubPath} />
                                            <path className="cmd-link card" d={layout.cardPath} />
                                            {layout.fanPaths.map((path, index) => <path key={index} className="cmd-link fan" d={path} />)}
                                            {!reducedMotion && (
                                                <g className="cmd-packets">
                                                    {[0, 1, 2].map((packet) => (
                                                        <circle key={packet} className={`cmd-packet ${flowing ? 'is-fast' : ''}`} r={flowing ? 3.6 : 2.6}>
                                                            <animateMotion dur={`${packetDuration}s`} begin={`${1.6 + order * 0.2 + packet * (packetDuration / 3)}s`} repeatCount="indefinite" path={layout.hubPath} />
                                                        </circle>
                                                    ))}
                                                    {layout.fanPaths.map((path, index) => (
                                                        <circle key={`fan-${index}`} className="cmd-packet fan" r={2.2}>
                                                            <animateMotion dur="2.8s" begin={`${2.2 + index * 0.55 + order * 0.3}s`} repeatCount="indefinite" path={path} />
                                                        </circle>
                                                    ))}
                                                </g>
                                            )}
                                        </g>
                                    )
                                })}
                            </svg>

                            {SQUADS.map((squad, index) => {
                                const layout = geometry.layouts[squad.id]
                                const state = squadState(squad, currentStage, membersBySquad[squad.id])
                                const fromX = layout.side * 160
                                const fromY = layout.hex.y < geometry.hub.y ? -120 : 120
                                return (
                                    <div key={squad.id}>
                                        <div className="cmd-node" style={{ left: layout.hex.x, top: layout.hex.y, '--fx': `${fromX}px`, '--fy': `${fromY}px`, '--delay': `${0.35 + index * 0.12}s` } as CSSProperties}>
                                            {squadNode(squad, state, 68)}
                                        </div>
                                        <div className="cmd-card-slot" style={{ left: layout.card.left, top: layout.card.top, width: layout.card.width, '--delay': `${1.15 + index * 0.1}s` } as CSSProperties}>
                                            <SquadCard squad={squad} members={membersBySquad[squad.id]} state={state} selectedId={selectedId} isMatch={isMatch} onSelect={onSelect} />
                                        </div>
                                        {fans[squad.id].map((item, fanIndex) => (
                                            <FanNode
                                                key={item.key}
                                                item={item}
                                                color={squad.color}
                                                matched={fanMatches(item)}
                                                onSelectEvidence={onSelectEvidence}
                                                style={{ left: layout.fanX, top: layout.fanYs[fanIndex], '--delay': `${1.45 + index * 0.08 + fanIndex * 0.05}s` } as CSSProperties}
                                            />
                                        ))}
                                        {layout.gate && (
                                            <span
                                                className={`cmd-gate ${approvalLocked ? 'is-locked' : 'is-open'}`}
                                                style={{ left: layout.gate.x, top: layout.gate.y } as CSSProperties}
                                                title={approvalLocked ? `Human approval required before release${approval ? ` (${approval.status})` : ''}` : `Released by human approval${approval?.reviewedBy ? ` from ${approval.reviewedBy}` : ''}`}
                                            >
                                                {approvalLocked ? <Lock size={12} /> : <LockOpen size={12} />}
                                                <span>Human approval</span>
                                            </span>
                                        )}
                                    </div>
                                )
                            })}

                            {hubNode && (
                                <div className="cmd-node cmd-hub-slot" style={{ left: geometry.hub.x, top: geometry.hub.y, '--fx': '0px', '--fy': '0px', '--delay': '0.05s' } as CSSProperties}>
                                    {hubNode}
                                </div>
                            )}
                        </>
                    )}

                    {compact && (
                        <div className="cmd-compact">
                            {hubNode && <div className="cmd-compact-hub">{hubNode}</div>}
                            {SQUADS.map((squad, index) => {
                                const state = squadState(squad, currentStage, membersBySquad[squad.id])
                                return (
                                    <div key={squad.id} className={`cmd-compact-row is-${state}`} style={{ '--squad-color': squad.color, '--delay': `${0.2 + index * 0.1}s` } as CSSProperties}>
                                        {squadNode(squad, state, 52)}
                                        <SquadCard
                                            squad={squad}
                                            members={membersBySquad[squad.id]}
                                            state={state}
                                            selectedId={selectedId}
                                            isMatch={isMatch}
                                            onSelect={onSelect}
                                            footer={
                                                <span className="cmd-compact-fans">
                                                    {squad.id === 'govern' && (
                                                        <span className={`cmd-gate inline ${approvalLocked ? 'is-locked' : 'is-open'}`}>
                                                            {approvalLocked ? <Lock size={11} /> : <LockOpen size={11} />}
                                                        </span>
                                                    )}
                                                    {fans[squad.id].map((item) => (
                                                        <FanNode key={item.key} item={item} color={squad.color} matched={fanMatches(item)} onSelectEvidence={onSelectEvidence} style={{}} />
                                                    ))}
                                                </span>
                                            }
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            )}

            <div className="cmd-command-bar">
                <form
                    className="cmd-search"
                    onSubmit={(event) => {
                        event.preventDefault()
                        submitSearch()
                    }}
                >
                    <Search size={16} />
                    <input
                        aria-label="Search the workforce"
                        placeholder="Search agents, evidence or gates… (Enter selects the first matching agent)"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                    />
                    {selected && onShowDetails && (
                        <button type="button" className="cmd-details" onClick={onShowDetails}>
                            {selected.name} details <ArrowDown size={13} />
                        </button>
                    )}
                </form>
                <div className="cmd-summary" aria-label="Recorded task counts">
                    <span><CircleDashed size={12} /> {runningCount} running</span>
                    <span>{completedCount} completed</span>
                    <span>{failedCount} failed</span>
                    <span className="cmd-summary-note">Recorded task states only · no live agent execution</span>
                </div>
            </div>
        </div>
    )
}

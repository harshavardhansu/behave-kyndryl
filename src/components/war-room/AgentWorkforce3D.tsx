import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Line, OrbitControls } from '@react-three/drei'
import { Vector3 } from 'three'
import type { Group, Mesh } from 'three'
import {
    Activity,
    Focus,
    Maximize,
    RotateCcw,
    Tags,
    Users,
} from 'lucide-react'
import type { Agent, AgentStatus, Evidence } from '../../types'
import { EmptyState } from '../ui'

type Point3 = [number, number, number]

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

/** Status palette aligned with the Kyndryl Bridge-style theme (teal accent, semantic states). */
function statusColor(status: AgentStatus) {
    if (status === 'Running') return '#29707A'
    if (status === 'Completed') return '#3C8A5A'
    if (status === 'Failed') return '#DA1E28'
    if (status === 'Queued' || status === 'Waiting for Human Approval' || status === 'Waiting for Evidence') return '#B28600'
    return '#8D8D8D'
}

const SCENE_BACKGROUND = '#F4F6F6'
const KYNDRYL_RED = '#FF462D'
const ACCENT = '#29707A'
const AGENT_RING_RADIUS = 4
const AGENT_HEIGHT = 0.22
const LABEL_OFFSET = 0.9

function rolePositions(agents: Agent[]) {
    const positions = new Map<string, Point3>()
    const specialists = agents.filter((agent) => agent.role !== 'orchestrator')
    specialists.forEach((agent, index) => {
        // Half-step offset keeps any single agent from sitting dead centre at the back of the ring,
        // where perspective compresses label spacing the most.
        const step = (Math.PI * 2) / Math.max(specialists.length, 1)
        const angle = index * step - Math.PI / 2 + step / 2
        positions.set(agent.id, [Math.cos(angle) * AGENT_RING_RADIUS, AGENT_HEIGHT, Math.sin(angle) * AGENT_RING_RADIUS])
    })
    if (agents.some((agent) => agent.role === 'orchestrator')) {
        positions.set(agents.find((agent) => agent.role === 'orchestrator')!.id, [0, 0.2, 0])
    }
    return positions
}

type EvidenceNodePlacement = { evidence: Evidence; owner: Agent; point: Point3 }
type ProjectedLabel = { key: string; point: Point3 }

function layoutEvidenceNodes(agents: Agent[], evidence: Evidence[], positions: Map<string, Point3>) {
    const evidenceById = new Map(evidence.map((record) => [record.id, record]))
    const nodes = new Map<string, EvidenceNodePlacement>()
    const specialists = agents.filter((agent) => agent.role !== 'orchestrator')
    specialists.forEach((agent) => {
        const source = positions.get(agent.id)
        if (!source) return
        const records = [...agent.inputs, ...agent.outputs].filter((id) => evidenceById.has(id) && !nodes.has(id))
        const baseAngle = Math.atan2(source[2], source[0])
        records.forEach((id, index) => {
            // Place evidence beside the owning agent (along the ring, slightly outward) so its chip
            // never sits underneath the agent's own label, which is drawn above the agent.
            const spread = 0.17 + index * 0.1
            const radius = AGENT_RING_RADIUS + 0.55 + index * 0.18
            const point: Point3 = [Math.cos(baseAngle + spread) * radius, 0.08, Math.sin(baseAngle + spread) * radius]
            nodes.set(id, { evidence: evidenceById.get(id)!, owner: agent, point })
        })
    })
    return nodes
}

/** Soft contact shadow so nodes read as resting on the floor. */
function ContactShadow({ radius, opacity = 0.12 }: { radius: number; opacity?: number }) {
    return (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.005, 0]}>
            <circleGeometry args={[radius, 40]} />
            <meshBasicMaterial color="#1B2B2E" transparent opacity={opacity} depthWrite={false} />
        </mesh>
    )
}

function SceneFloor() {
    return (
        <group position={[0, -0.02, 0]}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
                <circleGeometry args={[6.6, 96]} />
                <meshStandardMaterial color="#F1F5F5" roughness={0.95} metalness={0} />
            </mesh>
            {[1.55, AGENT_RING_RADIUS, AGENT_RING_RADIUS + 0.85].map((radius, index) => (
                <mesh key={radius} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.004, 0]}>
                    <ringGeometry args={[radius - (index === 1 ? 0.012 : 0.006), radius + (index === 1 ? 0.012 : 0.006), 128]} />
                    <meshBasicMaterial color={index === 1 ? '#B9CDD0' : '#D3DEE0'} transparent opacity={0.9} />
                </mesh>
            ))}
        </group>
    )
}

function WorkforceCore({ agent, reducedMotion, onSelect }: { agent: Agent; reducedMotion: boolean; onSelect: (agent: Agent) => void }) {
    const halo = useRef<Mesh>(null)
    const color = statusColor(agent.status)

    useFrame((state) => {
        if (reducedMotion || !halo.current) return
        const pulse = agent.status === 'Running' ? 1 + Math.sin(state.clock.elapsedTime * 2) * 0.04 : 1
        halo.current.scale.setScalar(pulse)
    })

    const select = (event: { stopPropagation: () => void }) => {
        event.stopPropagation()
        onSelect(agent)
    }

    return (
        <group position={[0, 0, 0]}>
            <ContactShadow radius={1.15} opacity={0.14} />
            {/* Base plinth */}
            <mesh position={[0, 0.13, 0]} onClick={select} onDoubleClick={select}>
                <cylinderGeometry args={[0.95, 1.02, 0.26, 64]} />
                <meshStandardMaterial color="#FFFFFF" roughness={0.55} metalness={0.05} />
            </mesh>
            {/* Teal hub */}
            <mesh position={[0, 0.38, 0]} onClick={select} onDoubleClick={select}>
                <cylinderGeometry args={[0.7, 0.78, 0.26, 64]} />
                <meshStandardMaterial color={ACCENT} roughness={0.4} metalness={0.15} />
            </mesh>
            {/* Status cap */}
            <mesh position={[0, 0.52, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                <circleGeometry args={[0.32, 48]} />
                <meshBasicMaterial color={agent.status === 'Running' ? '#FFFFFF' : color} transparent opacity={0.9} />
            </mesh>
            {/* Kyndryl red brand ring */}
            <mesh ref={halo} position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                <ringGeometry args={[1.2, 1.26, 96]} />
                <meshBasicMaterial color={KYNDRYL_RED} transparent opacity={0.9} />
            </mesh>
        </group>
    )
}

function AgentNode({
    agent,
    position,
    selected,
    reducedMotion,
    onSelect,
}: {
    agent: Agent
    position: Point3
    selected: boolean
    reducedMotion: boolean
    onSelect: (agent: Agent) => void
}) {
    const body = useRef<Group>(null)
    const color = statusColor(agent.status)
    const running = agent.status === 'Running'

    useFrame((state) => {
        if (!body.current) return
        const lift = selected ? 0.12 : 0
        if (reducedMotion || !running) {
            body.current.position.y = lift
            return
        }
        body.current.position.y = lift + (Math.sin(state.clock.elapsedTime * 2.4 + agent.phase) + 1) * 0.04
    })

    const select = (event: { stopPropagation: () => void }) => {
        event.stopPropagation()
        onSelect(agent)
    }

    return (
        <group position={[position[0], 0, position[2]]}>
            <ContactShadow radius={0.46} />
            {selected && (
                <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.006, 0]}>
                    <ringGeometry args={[0.5, 0.56, 64]} />
                    <meshBasicMaterial color={ACCENT} />
                </mesh>
            )}
            <group ref={body}>
                {/* White puck body */}
                <mesh position={[0, AGENT_HEIGHT, 0]} onClick={select} onDoubleClick={select}>
                    <cylinderGeometry args={[0.36, 0.38, 0.3, 48]} />
                    <meshStandardMaterial color="#FFFFFF" roughness={0.5} metalness={0.04} />
                </mesh>
                {/* Status band */}
                <mesh position={[0, AGENT_HEIGHT + 0.16, 0]} onClick={select} onDoubleClick={select}>
                    <cylinderGeometry args={[0.3, 0.33, 0.05, 48]} />
                    <meshStandardMaterial color={color} roughness={0.45} metalness={0.05} emissive={color} emissiveIntensity={running ? 0.35 : 0.08} />
                </mesh>
            </group>
        </group>
    )
}

function DependencyLink({ from, to, active }: { from: Point3; to: Point3; active: boolean }) {
    const particle = useRef<Mesh>(null)
    const start = useMemo(() => new Vector3(from[0], 0.06, from[2]), [from])
    const end = useMemo(() => new Vector3(to[0], 0.06, to[2]), [to])
    const points = useMemo<Point3[]>(() => [[start.x, start.y, start.z], [end.x, end.y, end.z]], [start, end])

    useFrame((state) => {
        if (!active || !particle.current) return
        const progress = (state.clock.elapsedTime * 0.25) % 1
        particle.current.position.lerpVectors(start, end, progress)
    })

    return (
        <>
            <Line points={points} color={active ? ACCENT : '#AEBFC2'} lineWidth={active ? 1.6 : 1} transparent opacity={active ? 0.9 : 0.55} />
            {active && (
                <mesh ref={particle} position={start}>
                    <sphereGeometry args={[0.06, 12, 12]} />
                    <meshBasicMaterial color={ACCENT} />
                </mesh>
            )}
        </>
    )
}

function EvidenceMarker({ point }: { point: Point3 }) {
    return (
        <group position={point}>
            <mesh>
                <cylinderGeometry args={[0.09, 0.09, 0.05, 24]} />
                <meshStandardMaterial color="#6F7F86" roughness={0.6} metalness={0.05} />
            </mesh>
        </group>
    )
}

function ProjectedAgentLabels({ labels, elements }: { labels: ProjectedLabel[]; elements: { current: Map<string, HTMLElement> } }) {
    const { camera, size } = useThree()
    const projected = useMemo(() => new Vector3(), [])
    useFrame(() => {
        labels.forEach(({ key, point }) => {
            const element = elements.current.get(key)
            if (!element) return
            projected.set(point[0], point[1], point[2]).project(camera)
            const visible = projected.z > -1 && projected.z < 1 && projected.x > -1.15 && projected.x < 1.15 && projected.y > -1.15 && projected.y < 1.15
            element.style.display = visible ? 'grid' : 'none'
            if (visible) {
                const x = (projected.x * 0.5 + 0.5) * size.width
                const y = (-projected.y * 0.5 + 0.5) * size.height
                element.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`
                // Nearer labels sit on top of farther ones.
                element.style.zIndex = String(Math.round((1 - projected.z) * 1000))
            }
        })
    })
    return null
}

const DEFAULT_TARGET: Point3 = [0, 0, -0.35]
const DEFAULT_CAMERA: Point3 = [0, 13.6, 6.4]

function CameraRig({ focus, focusVersion, resetVersion }: { focus: Point3 | null; focusVersion: number; resetVersion: number }) {
    const { camera, controls, size } = useThree()
    const previousReset = useRef(resetVersion)
    // The default framing is tuned for a ~1.35:1 panel. Narrower panels pull the camera back
    // so the whole ring (and its labels) still fits horizontally.
    const fit = size.width > 0 && size.height > 0 ? 1 + Math.max(0, 1.35 / (size.width / size.height) - 1) * 0.7 : 1
    const hasFocus = focus !== null
    const focusX = focus?.[0] ?? 0
    const focusY = focus?.[1] ?? 0
    const focusZ = focus?.[2] ?? 0
    useEffect(() => {
        const orbit = controls as unknown as { target?: { set: (x: number, y: number, z: number) => void }; update?: () => void } | null
        const resetRequested = previousReset.current !== resetVersion
        previousReset.current = resetVersion
        const target: Point3 = resetRequested || !hasFocus ? DEFAULT_TARGET : [focusX, focusY, focusZ]
        if (hasFocus && !resetRequested) camera.position.set(focusX * 1.2, focusY + 6.4, focusZ * 1.2 + 4)
        else camera.position.set(
            DEFAULT_TARGET[0] + (DEFAULT_CAMERA[0] - DEFAULT_TARGET[0]) * fit,
            DEFAULT_TARGET[1] + (DEFAULT_CAMERA[1] - DEFAULT_TARGET[1]) * fit,
            DEFAULT_TARGET[2] + (DEFAULT_CAMERA[2] - DEFAULT_TARGET[2]) * fit,
        )
        camera.lookAt(...target)
        orbit?.target?.set(...target)
        orbit?.update?.()
    }, [camera, controls, fit, focusVersion, focusX, focusY, focusZ, hasFocus, resetVersion])
    return null
}

function WorkforceScene({
    agents,
    evidence,
    selectedId,
    reducedMotion,
    focus,
    focusVersion,
    resetVersion,
    projectedLabels,
    labelElements,
    onSelect,
}: {
    agents: Agent[]
    evidence: Evidence[]
    selectedId: string | null
    reducedMotion: boolean
    focus: Point3 | null
    focusVersion: number
    resetVersion: number
    projectedLabels: ProjectedLabel[]
    labelElements: { current: Map<string, HTMLElement> }
    onSelect: (agent: Agent) => void
}) {
    const points = useMemo(() => rolePositions(agents), [agents])
    const orchestrator = agents.find((agent) => agent.role === 'orchestrator')
    const specialists = agents.filter((agent) => agent.role !== 'orchestrator')
    const byId = new Map(agents.map((agent) => [agent.id, agent]))
    const evidenceNodes = useMemo(() => layoutEvidenceNodes(agents, evidence, points), [agents, evidence, points])

    return (
        <Canvas camera={{ position: DEFAULT_CAMERA, fov: 42 }} dpr={[1, 1.75]} gl={{ antialias: true, alpha: false }} fallback={(
            <div className="workforce-canvas-fallback">
                <div className="workforce-webgl-fallback">WebGL unavailable / showing the 2D workforce fallback</div>
                <WorkforceList agents={agents} selectedId={selectedId} onSelect={onSelect} />
            </div>
        )}>
            <color attach="background" args={[SCENE_BACKGROUND]} />
            <fog attach="fog" args={[SCENE_BACKGROUND, 16, 26]} />
            <hemisphereLight args={['#FFFFFF', '#DCE5E6', 1.15]} />
            <directionalLight position={[5, 10, 6]} intensity={1.1} color="#FFFFFF" />
            <directionalLight position={[-6, 4, -4]} intensity={0.35} color="#E6F0F1" />
            <SceneFloor />
            {orchestrator && specialists.map((agent) => {
                const point = points.get(agent.id)
                if (!point) return null
                return (
                    <Line key={`spoke-${agent.id}`} points={[[0, 0.03, 0], [point[0] * 0.9, 0.03, point[2] * 0.9]]} color="#C9D7D9" lineWidth={1} transparent opacity={0.8} />
                )
            })}
            {specialists.flatMap((agent) => agent.dependencies.map((dependencyId) => {
                const dependency = byId.get(dependencyId)
                const from = dependency ? points.get(dependency.id) : undefined
                const to = points.get(agent.id)
                if (!dependency || !from || !to || dependency.role === 'orchestrator') return null
                return <DependencyLink key={`${dependency.id}-${agent.id}`} from={from} to={to} active={dependency.status === 'Running' || agent.status === 'Running'} />
            }))}
            {[...evidenceNodes.entries()].map(([id, entry]) => {
                const ownerPoint = points.get(entry.owner.id)
                if (!ownerPoint) return null
                return (
                    <group key={id}>
                        <Line points={[[ownerPoint[0], 0.05, ownerPoint[2]], [entry.point[0], 0.05, entry.point[2]]]} color="#C3CED0" lineWidth={0.8} transparent opacity={0.7} dashed dashSize={0.08} gapSize={0.06} />
                        <EvidenceMarker point={entry.point} />
                    </group>
                )
            })}
            {orchestrator && <WorkforceCore agent={orchestrator} reducedMotion={reducedMotion} onSelect={onSelect} />}
            {specialists.map((agent) => {
                const point = points.get(agent.id)
                if (!point) return null
                return (
                    <AgentNode key={agent.id} agent={agent} position={point} selected={selectedId === agent.id} reducedMotion={reducedMotion} onSelect={onSelect} />
                )
            })}
            <ProjectedAgentLabels labels={projectedLabels} elements={labelElements} />
            <CameraRig focus={focus} focusVersion={focusVersion} resetVersion={resetVersion} />
            <OrbitControls makeDefault target={DEFAULT_TARGET} enableDamping dampingFactor={0.08} minDistance={6} maxDistance={30} minPolarAngle={Math.PI * 0.12} maxPolarAngle={Math.PI * 0.42} />
        </Canvas>
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

export function AgentWorkforce3D({
    agents,
    evidence,
    selectedId,
    onSelect,
    onSelectEvidence,
}: {
    agents: Agent[]
    evidence: Evidence[]
    selectedId: string | null
    onSelect: (agent: Agent) => void
    onSelectEvidence: (evidenceId: string) => void
}) {
    const [view, setView] = useState<'3d' | '2d'>(() =>
        window.matchMedia('(max-width: 700px), (prefers-reduced-motion: reduce)').matches ? '2d' : '3d'
    )
    const [statusFilter, setStatusFilter] = useState('All statuses')
    const [roleFilter, setRoleFilter] = useState('All roles')
    const [showLabels, setShowLabels] = useState(true)
    const [resetVersion, setResetVersion] = useState(0)
    const [focusVersion, setFocusVersion] = useState(0)
    const [fullscreen, setFullscreen] = useState(false)
    const [webglAvailable, setWebglAvailable] = useState<boolean | null>(null)
    const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    const viewport = useRef<HTMLDivElement>(null)
    const labelElements = useRef(new Map<string, HTMLElement>())

    useEffect(() => {
        const query = window.matchMedia('(prefers-reduced-motion: reduce)')
        const update = () => setReducedMotion(query.matches)
        query.addEventListener('change', update)
        return () => query.removeEventListener('change', update)
    }, [])

    useEffect(() => {
        const updateFullscreen = () => setFullscreen(document.fullscreenElement === viewport.current)
        document.addEventListener('fullscreenchange', updateFullscreen)
        return () => document.removeEventListener('fullscreenchange', updateFullscreen)
    }, [])

    useEffect(() => {
        const frame = requestAnimationFrame(() => {
            const probe = document.createElement('canvas')
            const context = probe.getContext('webgl2') ?? probe.getContext('webgl')
            setWebglAvailable(Boolean(context))
            context?.getExtension('WEBGL_lose_context')?.loseContext()
        })
        return () => cancelAnimationFrame(frame)
    }, [])

    const roles = useMemo(() => [...new Set(agents.map((agent) => agent.name))], [agents])
    const visibleAgents = useMemo(() => agents.filter((agent) =>
        (statusFilter === 'All statuses' || agent.status === statusFilter) &&
        (roleFilter === 'All roles' || agent.name === roleFilter)
    ), [agents, roleFilter, statusFilter])
    const orchestrator = agents.find((agent) => agent.role === 'orchestrator')
    const displayAgents = useMemo(() => {
        const found = visibleAgents.find((agent) => agent.role === 'orchestrator')
        return found || !orchestrator ? visibleAgents : [orchestrator, ...visibleAgents]
    }, [orchestrator, visibleAgents])
    const selected = agents.find((agent) => agent.id === selectedId)
    const has3dView = view === '3d' && webglAvailable === true
    const allPositions = useMemo(() => rolePositions(agents), [agents])
    const displayPositions = useMemo(() => rolePositions(displayAgents), [displayAgents])
    const evidenceNodes = useMemo(() => layoutEvidenceNodes(displayAgents, evidence, displayPositions), [displayAgents, displayPositions, evidence])
    const projectedLabels = useMemo(() => [
        ...displayAgents
            .filter((agent) => agent.role !== 'orchestrator')
            .flatMap((agent) => {
                const point = displayPositions.get(agent.id)
                if (!point) return []
                // Labels at the back of the ring sit closest together on screen; lift the left-hand ones.
                const atBack = point[2] < -AGENT_RING_RADIUS * 0.6 && Math.abs(point[0]) < AGENT_RING_RADIUS * 0.45
                const lift = atBack && point[0] < 0 ? 1.35 : 0
                return [{ key: `agent:${agent.id}`, point: [point[0], point[1] + LABEL_OFFSET + lift, point[2]] as Point3 }]
            }),
        ...[...evidenceNodes.values()].map(({ evidence: record, point }) => ({ key: `evidence:${record.id}`, point })),
    ], [displayAgents, displayPositions, evidenceNodes])
    const focus = selected ? allPositions.get(selected.id) ?? null : null

    function selectAgent(agent: Agent) {
        onSelect(agent)
        setFocusVersion((value) => value + 1)
    }

    async function toggleFullscreen() {
        if (!viewport.current) return
        try {
            if (document.fullscreenElement) await document.exitFullscreen()
            else await viewport.current.requestFullscreen()
        } catch {
            setFullscreen(false)
        }
    }

    if (!agents.length) {
        return (
            <div className="workforce-empty">
                <EmptyState title="No agent tasks recorded" description="The backend has not created specialist task records for this incident yet. Start an investigation to see its recorded workforce." />
            </div>
        )
    }

    const runningCount = agents.filter((agent) => agent.status === 'Running').length
    const completedCount = agents.filter((agent) => agent.status === 'Completed').length
    const failedCount = agents.filter((agent) => agent.status === 'Failed').length

    return (
        <div className={`workforce-shell ${fullscreen ? 'is-fullscreen' : ''}`} ref={viewport}>
            <div className="workforce-toolbar">
                <div className="workforce-mode-switch" role="group" aria-label="Workforce view">
                    <button aria-pressed={view === '3d'} onClick={() => setView('3d')}><Focus size={14} /> 3D workforce</button>
                    <button aria-pressed={view === '2d'} onClick={() => setView('2d')}><Users size={14} /> 2D list</button>
                </div>
                <label className="workforce-filter-label">Role
                    <select aria-label="Filter workforce by role" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                        <option>All roles</option>
                        {roles.map((role) => <option key={role}>{role}</option>)}
                    </select>
                </label>
                <label className="workforce-filter-label">Status
                    <select aria-label="Filter workforce by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                        <option>All statuses</option>
                        {STATUS_OPTIONS.map((status) => <option key={status}>{status}</option>)}
                    </select>
                </label>
                <button className={`workforce-tool ${showLabels ? 'active' : ''}`} aria-label="Toggle agent labels" aria-pressed={showLabels} disabled={!has3dView} onClick={() => setShowLabels((value) => !value)}><Tags size={14} /> Labels</button>
                <button className="workforce-tool" aria-label="Focus selected agent" disabled={!selected || !has3dView} onClick={() => setFocusVersion((value) => value + 1)}><Focus size={14} /> Focus</button>
                <button className="workforce-tool" aria-label="Reset workforce camera" disabled={!has3dView} onClick={() => setResetVersion((value) => value + 1)}><RotateCcw size={14} /> Reset</button>
                <button className="workforce-tool" aria-label={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'} onClick={() => void toggleFullscreen()}><Maximize size={14} /> Fullscreen</button>
            </div>
            <div className="workforce-stage">
                {view === '3d' && webglAvailable === null ? (
                    <div className="workforce-preparing">
                        <div className="workforce-preparing-label">Preparing 3D view / backend snapshot remains available</div>
                        <WorkforceList agents={displayAgents} selectedId={selectedId} onSelect={selectAgent} />
                    </div>
                ) : view === '3d' && webglAvailable ? (
                    <WorkforceScene agents={displayAgents} evidence={evidence} selectedId={selectedId} reducedMotion={reducedMotion} focus={focus} focusVersion={focusVersion} resetVersion={resetVersion} projectedLabels={projectedLabels} labelElements={labelElements} onSelect={selectAgent} />
                ) : (
                    <>
                        {view === '3d' && <div className="workforce-fallback-note">WebGL unavailable / accessible 2D workforce</div>}
                        <WorkforceList agents={displayAgents} selectedId={selectedId} onSelect={selectAgent} />
                    </>
                )}
                {view === '3d' && webglAvailable === true && showLabels && (
                    <div className="workforce-label-layer" aria-label="Agent and evidence labels">
                        {displayAgents.filter((agent) => agent.role !== 'orchestrator').map((agent) => (
                            <button
                                key={`agent:${agent.id}`}
                                ref={(element) => {
                                    if (element) labelElements.current.set(`agent:${agent.id}`, element)
                                    else labelElements.current.delete(`agent:${agent.id}`)
                                }}
                                className={`workforce-agent-label ${selectedId === agent.id ? 'selected' : ''}`}
                                style={{ '--status-color': statusColor(agent.status) } as CSSProperties}
                                title={`${agent.name} / ${agent.status}`}
                                onClick={() => selectAgent(agent)}
                            ><strong>{agent.name}</strong><span>{agent.status}</span></button>
                        ))}
                        {[...evidenceNodes.values()].filter(({ owner }) => owner.id === selectedId).map(({ evidence: record }) => (
                            <button
                                key={`evidence:${record.id}`}
                                ref={(element) => {
                                    if (element) labelElements.current.set(`evidence:${record.id}`, element)
                                    else labelElements.current.delete(`evidence:${record.id}`)
                                }}
                                className="workforce-evidence-label"
                                title={`${record.title} / ${record.source}`}
                                onClick={() => onSelectEvidence(record.id)}
                            >{record.id}</button>
                        ))}
                    </div>
                )}
                {orchestrator && view === '3d' && (
                    <div className="workforce-core-label" aria-label={`Orchestrator status ${orchestrator.status}`}>
                        <span>ORCHESTRATOR</span>
                        <strong>{orchestrator.status}</strong>
                    </div>
                )}
                <div className="workforce-live-summary" aria-label="Recorded task counts">
                    <span><Activity size={12} /> {runningCount} running</span>
                    <span>{completedCount} completed</span>
                    <span>{failedCount} failed</span>
                </div>
                <div className="workforce-scene-note">Backend snapshot · {agents.length} task records · activity shown only for recorded states</div>
            </div>
        </div>
    )
}
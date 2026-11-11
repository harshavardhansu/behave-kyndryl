import { useState } from 'react'
import { Activity, FlaskConical, Play, RotateCcw, Server } from 'lucide-react'
import type { Incident, SandboxMeasurement } from '../../types'
import { post } from '../../lib/api'
import { errorMessage, time } from '../../lib/format'
import { useWorkspace } from '../../context'
import { Badge, Button } from '../ui'
import './payment-sandbox.css'

function MeasurementBars({ measurement }: { measurement: SandboxMeasurement }) {
    const total = Math.max(measurement.requests, 1)
    return (
        <div className="sandbox-bars" aria-label={`${measurement.succeeded} succeeded, ${measurement.errors} failed`}>
            {Array.from({ length: total }, (_, index) => (
                <i key={index} className={index < measurement.succeeded ? 'ok' : 'fail'} style={{ animationDelay: `${index * 18}ms` }} />
            ))}
        </div>
    )
}

/** Live controls for the real, local Payment API sandbox (backend/payment_local.py). */
export function PaymentSandboxPanel({ incident }: { incident: Incident }) {
    const { data, can, notify, refresh } = useWorkspace()
    const [busy, setBusy] = useState('')
    const sandbox = data.paymentSandbox
    const measurements = (data.sandboxMeasurements ?? []).filter((item) => !item.incidentId || item.incidentId === incident.id)
    const latest = measurements[measurements.length - 1]
    const allowed = can('workflow:run', 'Sandbox')
    const active = sandbox?.activeConfig

    async function run(path: string, label: string, body: unknown = {}) {
        setBusy(label)
        try {
            const result = await post<{ measurement?: SandboxMeasurement }>(path, body)
            await refresh()
            if (result.measurement) {
                const m = result.measurement
                notify(`Measured: ${m.errors}/${m.requests} requests failed (pool ${m.poolSize}). Saved as evidence.`, m.errors > 0)
            } else notify(`${label} done.`)
        } catch (failure) {
            notify(errorMessage(failure), true)
        } finally {
            setBusy('')
        }
    }

    if (sandbox?.mode !== 'local') {
        return (
            <section className="sandbox-panel">
                <p className="sandbox-note">The local Payment API sandbox is not enabled (container mode). See README for the Podman setup.</p>
            </section>
        )
    }

    return (
        <section className="sandbox-panel" aria-label="Payment API sandbox">
            <div className="sandbox-head">
                <div className="sandbox-title">
                    <Server size={16} />
                    <strong>Live Payment API sandbox</strong>
                    <Badge tone={sandbox.running ? 'success' : 'neutral'}>{sandbox.running ? 'Running' : 'Stopped'}</Badge>
                    <span className="sandbox-real">REAL · MEASURED</span>
                </div>
                <div className="sandbox-config">
                    {active ? (
                        <>
                            <span>Release <b>{active.release}</b></span>
                            <span className={active.pool_size < 20 ? 'is-bad' : 'is-good'}>Pool size <b>{active.pool_size}</b></span>
                            <span>Feature X <b>{active.release === '3.8.1' ? 'on' : 'off'}</b></span>
                            <span className="mono">{sandbox.url}</span>
                        </>
                    ) : (
                        <span className="muted">Not running. Start it to reproduce the incident live.</span>
                    )}
                </div>
            </div>
            <div className="sandbox-body">
                <div className="sandbox-actions">
                    <Button variant={sandbox.running ? 'secondary' : 'primary'} disabled={!allowed || Boolean(busy)} busy={busy === 'Start'} onClick={() => void run('/sandbox/payment/start', 'Start')}>
                        <Play size={14} /> {sandbox.running ? 'Running' : 'Start sandbox'}
                    </Button>
                    <Button variant={sandbox.running ? 'primary' : 'secondary'} disabled={!allowed || !sandbox.running || Boolean(busy)} busy={busy === 'Workload'} onClick={() => void run('/sandbox/payment/workload', 'Workload', { incidentId: incident.id })}>
                        <Activity size={14} /> Run workload (50 requests)
                    </Button>
                    <Button variant="ghost" disabled={!allowed || Boolean(busy)} busy={busy === 'Reset'} onClick={() => void run('/sandbox/payment/reset', 'Reset')}>
                        <RotateCcw size={14} /> Reset to faulty release
                    </Button>
                    <p className="sandbox-help">
                        <FlaskConical size={13} /> Each run fires 50 simultaneous requests at <span className="mono">GET /payments/summary</span>. Every request holds a database connection for 0.3 s and waits at most 2 s for one, so a pool of 5 runs out and some requests fail with real HTTP 500s.
                    </p>
                </div>
                <div className="sandbox-result">
                    {latest ? (
                        <>
                            <div className="sandbox-result-head">
                                <span>Latest run · {time(latest.measuredAt)} · pool {latest.poolSize} · release {latest.release}</span>
                                <span className={latest.errors ? 'sandbox-verdict bad' : 'sandbox-verdict good'}>{latest.errors ? `${latest.errors} failed` : 'All succeeded'}</span>
                            </div>
                            <MeasurementBars measurement={latest} />
                            <div className="sandbox-stats">
                                <span><b>{latest.succeeded}</b> OK</span>
                                <span><b>{latest.errors}</b> HTTP 5xx</span>
                                <span><b>{latest.errorRate}%</b> error rate</span>
                                <span>p95 <b>{latest.p95Ms} ms</b></span>
                                <span>Feature X <b>{latest.featureX ? 'available' : 'not available'}</b></span>
                            </div>
                            {measurements.length > 1 && (
                                <ol className="sandbox-history">
                                    {[...measurements].reverse().slice(0, 5).map((item) => (
                                        <li key={item.id}>
                                            <span className="mono">{time(item.measuredAt)}</span>
                                            <span>pool {item.poolSize}</span>
                                            <span className={item.errors ? 'bad' : 'good'}>{item.errors}/{item.requests} failed</span>
                                            <span className="muted">{item.purpose}</span>
                                        </li>
                                    ))}
                                </ol>
                            )}
                        </>
                    ) : (
                        <p className="sandbox-empty">No measurement yet. Start the sandbox and run the workload: the results are saved as evidence that the agents will read.</p>
                    )}
                </div>
            </div>
        </section>
    )
}

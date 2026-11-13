import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, CloudUpload, RefreshCw } from 'lucide-react'
import { post, request } from '../../lib/api'
import { dateTime, errorMessage } from '../../lib/format'
import { useWorkspace } from '../../context'
import { Badge, Button, Notice } from '../ui'

interface FoundryAgentRow {
  role: string
  name: string
  squad: string
  foundryName: string
  provisioned: boolean
  version: string | null
  syncedAt: string | null
  runs: number
  lastRunAt: string | null
  humanApprovalRequired: boolean
}

interface FoundryStatus {
  agents: FoundryAgentRow[]
  total: number
  provisioned: number
  mode: 'simulated' | 'model' | 'foundry-partial' | 'foundry'
  status: string
  configured: boolean
  project: string
  modelDeployment: string
  agentMode: string
  authentication: string
}

const MODE_LABEL: Record<FoundryStatus['mode'], string> = {
  simulated: 'Simulated planner',
  model: 'Azure OpenAI model',
  'foundry-partial': 'Foundry agents (partial)',
  foundry: 'Foundry agents',
}

/** Shows which agents really exist in Azure AI Foundry and lets an administrator create them. */
export function FoundryAgentsPanel() {
  const { can, notify, refresh } = useWorkspace()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const status = useQuery({ queryKey: ['foundry-agents'], queryFn: () => request<FoundryStatus>('/foundry/agents') })

  async function sync(force: boolean) {
    setBusy(true)
    try {
      const result = await post<FoundryStatus & { results: { action: string }[] }>('/foundry/agents/sync', { force })
      queryClient.setQueryData(['foundry-agents'], result)
      await refresh()
      const changed = result.results.filter((item) => item.action !== 'unchanged').length
      notify(`Foundry sync done: ${changed} agent(s) created or updated, ${result.results.length - changed} unchanged.`)
    } catch (failure) {
      notify(errorMessage(failure), true)
    } finally {
      setBusy(false)
    }
  }

  const data = status.data
  if (status.isError) return <Notice title="Foundry status unavailable" tone="error">{errorMessage(status.error)}</Notice>
  if (!data) return <p className="muted">Loading Foundry status…</p>
  return (
    <div className="foundry-panel">
      <div className="foundry-head">
        <div>
          <h3><Bot size={16} /> Agents in Azure AI Foundry</h3>
          <p>{data.status}</p>
          <p className="muted">
            Running as: <strong>{MODE_LABEL[data.mode]}</strong>
            {data.project && <> · project <span className="mono">{data.project}</span></>}
            {data.modelDeployment && <> · model <span className="mono">{data.modelDeployment}</span></>}
            {' '}· sign-in: {data.authentication}
          </p>
        </div>
        <div className="foundry-actions">
          <Button variant="primary" busy={busy} disabled={!data.configured || !can('admin:write')} onClick={() => void sync(false)}>
            <CloudUpload size={15} /> Sync agents to Foundry
          </Button>
          <Button variant="ghost" disabled={busy || !data.configured || !can('admin:write')} onClick={() => void sync(true)}>
            <RefreshCw size={14} /> Recreate all
          </Button>
        </div>
      </div>
      <table className="foundry-table">
        <thead>
          <tr><th>Agent</th><th>Squad</th><th>Foundry name</th><th>State</th><th>Runs</th><th>Last synced</th></tr>
        </thead>
        <tbody>
          {data.agents.map((agent) => (
            <tr key={agent.role}>
              <td><strong>{agent.name}</strong>{agent.humanApprovalRequired && <small> · human approval</small>}</td>
              <td>{agent.squad.replace(' Squad', '')}</td>
              <td className="mono">{agent.foundryName}</td>
              <td>{agent.provisioned ? <Badge tone="success">v{agent.version}</Badge> : <Badge tone="neutral">Not created</Badge>}</td>
              <td className="mono">{agent.runs}</td>
              <td>{agent.syncedAt ? dateTime(agent.syncedAt) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.configured && data.provisioned === 0 && (
        <Notice title="Before you sync">
          Foundry agents need Microsoft Entra sign-in: run <span className="mono">az login</span> on the computer that runs the backend, and make
          sure your account has the <strong>Azure AI User</strong> role on the project. An API key is not accepted for agents.
        </Notice>
      )}
    </div>
  )
}

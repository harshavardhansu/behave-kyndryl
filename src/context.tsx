import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, LogIn, RefreshCw, X } from 'lucide-react'
import type { Environment, Session, Snapshot } from './types'
import { ApiError, downloadReport, post, request, setSession } from './lib/api'
import { errorMessage } from './lib/format'
import { BrandMark, Button, LoadingState, Notice, Select } from './components/ui'

export type WorkflowAction =
  | 'start-investigation'
  | 'pause'
  | 'resume'
  | 'cancel'
  | 'retry'
  | 'generate-fix'
  | 'run-validation'
  | 'request-approval'
  | 'approve'
  | 'reject'
  | 'deploy'
  | 'rollback'
  | 'verify'
  | 'close'
  | 'reopen'
  | 'assign'
  | 'escalate'
type Toast = { id: number; message: string; error: boolean }
type ActionDialog = { incidentId: string; action: WorkflowAction } | null

interface WorkspaceContextType {
  data: Snapshot
  session: Session
  environment: Environment
  setEnvironment: (environment: Environment) => void
  selectedIncidentId: string
  selectIncident: (id: string) => void
  can: (permission: string, environment?: string) => boolean
  notify: (message: string, error?: boolean) => void
  refresh: () => Promise<void>
  refreshing: boolean
  switchRole: (role: string) => Promise<void>
  signOut: () => Promise<void>
  exportReport: (format: 'json' | 'csv', incidentId?: string) => Promise<void>
  runAction: (
    incidentId: string,
    action: WorkflowAction,
    details?: Record<string, string>
  ) => Promise<void>
  actionPending: boolean
  createOpen: boolean
  setCreateOpen: (open: boolean) => void
  evidenceFor: string | null
  setEvidenceFor: (id: string | null) => void
  actionDialog: ActionDialog
  setActionDialog: (dialog: ActionDialog) => void
}

const WorkspaceContext = createContext<WorkspaceContextType | null>(null)

export function useWorkspace() {
  const context = useContext(WorkspaceContext)
  if (!context) throw new Error('Workspace context is unavailable.')
  return context
}

export function useIncident() {
  const { data, selectedIncidentId } = useWorkspace()
  return (
    data.incidents.find((incident) => incident.id === selectedIncidentId) ??
    data.incidents[0]
  )
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [environment, setEnvironment] = useState<Environment>('Production')
  const [selectedIncidentId, setSelectedIncidentId] = useState(
    localStorage.getItem('agentica-incident') ?? 'INC-1042'
  )
  const [toasts, setToasts] = useState<Toast[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [evidenceFor, setEvidenceFor] = useState<string | null>(null)
  const [actionDialog, setActionDialog] = useState<ActionDialog>(null)
  const [signInRole, setSignInRole] = useState('Incident Manager')
  const [signInError, setSignInError] = useState('')
  const [signingIn, setSigningIn] = useState(false)
  const sessionQuery = useQuery<Session | null>({
    queryKey: ['session'],
    retry: false,
    staleTime: Infinity,
    queryFn: async () => {
      if (sessionStorage.getItem('agentica-signed-out')) return null
      const health = await request<{ mode: string }>('/health')
      let result: Session
      if (
        !sessionStorage.getItem('agentica-bootstrapped') &&
        health.mode === 'demo'
      ) {
        result = await post<Session>('/auth/demo', { role: 'Incident Manager' })
        sessionStorage.setItem('agentica-bootstrapped', 'true')
      } else {
        try {
          result = await request<Session>('/auth/session')
        } catch (error) {
          if (error instanceof ApiError && error.status === 401) return null
          throw error
        }
      }
      setSession(result)
      return result
    },
  })
  const dataQuery = useQuery<Snapshot>({
    queryKey: ['workspace'],
    queryFn: () => request('/workspace'),
    enabled: Boolean(sessionQuery.data),
    refetchInterval: (query) =>
      query.state.data?.incidents.some(
        (incident) => incident.workflowStatus === 'Running'
      )
        ? 1200
        : 30_000,
  })

  function notify(message: string, error = false) {
    setToasts((current) => [
      ...current.slice(-2),
      { id: Date.now() + Math.random(), message, error },
    ])
  }

  useEffect(() => {
    if (!toasts.length) return
    const timer = setTimeout(
      () => setToasts((current) => current.slice(1)),
      6500
    )
    return () => clearTimeout(timer)
  }, [toasts])

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ['workspace'] })
  }

  async function switchRole(role: string) {
    const session = await post<Session>('/auth/demo', { role })
    setSession(session)
    queryClient.setQueryData(['session'], session)
    sessionStorage.removeItem('agentica-signed-out')
    sessionStorage.setItem('agentica-bootstrapped', 'true')
    await refresh()
    notify(
      `Demo identity: ${session.user.name} (${role}). Permissions are enforced by the API.`
    )
  }

  async function signOut() {
    await post('/auth/logout', {})
    setSession(null)
    sessionStorage.setItem('agentica-signed-out', 'true')
    queryClient.setQueryData(['session'], null)
    queryClient.removeQueries({ queryKey: ['workspace'] })
  }

  const mutation = useMutation({
    mutationFn: ({
      incidentId,
      action,
      details,
    }: {
      incidentId: string
      action: WorkflowAction
      details?: Record<string, string>
    }) =>
      post<{ message: string }>(
        `/incidents/${incidentId}/actions`,
        { action, ...details },
        true
      ),
    onSuccess: async (result) => {
      await refresh()
      notify(result.message)
    },
  })

  async function runAction(
    incidentId: string,
    action: WorkflowAction,
    details?: Record<string, string>
  ) {
    await mutation.mutateAsync({ incidentId, action, details })
  }

  async function exportReport(format: 'json' | 'csv', incidentId = '') {
    try {
      await downloadReport(
        format,
        incidentId,
        incidentId ? 'All environments' : environment
      )
      await refresh()
      notify(
        'Report exported. Synthetic records and evidence provenance are labeled in the file.'
      )
    } catch (error) {
      notify(errorMessage(error), true)
    }
  }

  if (sessionQuery.isLoading || (sessionQuery.data && dataQuery.isLoading))
    return <LoadingState />
  if (sessionQuery.error || (dataQuery.error && !dataQuery.data))
    return (
      <div className="connection-error">
        <div className="loading-brand">
          <BrandMark />
        </div>
        <Notice title="Workspace unavailable" tone="error">
          {errorMessage(sessionQuery.error ?? dataQuery.error)}
        </Notice>
        <Button
          onClick={() => {
            void sessionQuery.refetch()
            void dataQuery.refetch()
          }}
        >
          <RefreshCw size={16} /> Retry connection
        </Button>
        <p className="muted">
          The API must be running at 127.0.0.1:8000. No offline success is
          simulated.
        </p>
      </div>
    )
  if (!sessionQuery.data)
    return (
      <div className="access-screen">
        <div className="access-panel">
          <div className="loading-brand">
            <BrandMark />
          </div>
          <p className="eyebrow">Northstar Commerce / Local demonstration</p>
          <h1>Workspace access</h1>
          <Notice title="Demo identities only">
            These local personas are not production authentication. Entra access
            tokens are required when the API runs in production mode.
          </Notice>
          <label className="field-label">
            Demo role
            <Select
              label="Sign-in demo role"
              value={signInRole}
              onChange={(event) => setSignInRole(event.target.value)}
            >
              {[
                'Incident Manager',
                'Change Approver',
                'Administrator',
                'Viewer',
                'Developer',
                'QA Engineer',
                'SRE / Operator',
                'Security Analyst',
              ].map((role) => (
                <option key={role}>{role}</option>
              ))}
            </Select>
          </label>
          {signInError && (
            <Notice title="Sign-in unavailable" tone="error">
              {signInError}
            </Notice>
          )}
          <Button
            variant="primary"
            busy={signingIn}
            onClick={async () => {
              setSigningIn(true)
              setSignInError('')
              try {
                await switchRole(signInRole)
              } catch (error) {
                setSignInError(errorMessage(error))
              } finally {
                setSigningIn(false)
              }
            }}
          >
            <LogIn size={18} /> Enter workspace
          </Button>
        </div>
      </div>
    )
  if (!dataQuery.data) return <LoadingState />
  const session = sessionQuery.data
  return (
    <WorkspaceContext.Provider
      value={{
        data: dataQuery.data,
        session,
        environment,
        setEnvironment,
        selectedIncidentId,
        selectIncident: (id) => {
          setSelectedIncidentId(id)
          localStorage.setItem('agentica-incident', id)
        },
        can: (permission, target) =>
          session.user.permissions.includes(permission) &&
          (!target ||
            session.user.environments.includes(target as Environment)),
        notify,
        refresh,
        refreshing: dataQuery.isFetching,
        switchRole,
        signOut,
        exportReport,
        runAction,
        actionPending: mutation.isPending,
        createOpen,
        setCreateOpen,
        evidenceFor,
        setEvidenceFor,
        actionDialog,
        setActionDialog,
      }}
    >
      {dataQuery.error && (
        <div className="connection-warning" role="alert">
          Refresh failed. Displaying the last loaded records.{' '}
          <button onClick={() => void refresh()}>Retry</button>
        </div>
      )}
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast ${toast.error ? 'toast-error' : ''}`}
          >
            {toast.error ? (
              <CircleAlert size={19} />
            ) : (
              <CheckCircle2 size={19} />
            )}
            <span>{toast.message}</span>
            <button
              aria-label="Dismiss notification"
              onClick={() =>
                setToasts((current) =>
                  current.filter((item) => item.id !== toast.id)
                )
              }
            >
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
    </WorkspaceContext.Provider>
  )
}

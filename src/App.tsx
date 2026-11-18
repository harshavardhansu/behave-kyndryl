import { Component, lazy } from 'react'
import type { ReactNode } from 'react'
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as Tooltip from '@radix-ui/react-tooltip'
import { WorkspaceProvider } from './context'
import { Shell, navigation } from './components/Shell'
import { BrandMark, Button, EmptyState, PageHeader } from './components/ui'
import { WorkspaceDialogs } from './components/Forms'
import { ApiError } from './lib/api'

// Each page is its own chunk, loaded when first visited, so phones download only what they show.
const Overview = lazy(() => import('./pages/Overview').then((module) => ({ default: module.Overview })))
const Incidents = lazy(() => import('./pages/Incidents').then((module) => ({ default: module.Incidents })))
const IncidentDetail = lazy(() => import('./pages/Incidents').then((module) => ({ default: module.IncidentDetail })))
const WarRoom = lazy(() => import('./pages/WarRoom').then((module) => ({ default: module.WarRoom })))
const Investigations = lazy(() => import('./pages/Investigations').then((module) => ({ default: module.Investigations })))
const Agents = lazy(() => import('./pages/Agents').then((module) => ({ default: module.Agents })))
const Repositories = lazy(() => import('./pages/Repositories').then((module) => ({ default: module.Repositories })))
const Testing = lazy(() => import('./pages/Testing').then((module) => ({ default: module.Testing })))
const Security = lazy(() => import('./pages/Security').then((module) => ({ default: module.Security })))
const Errors = lazy(() => import('./pages/Errors').then((module) => ({ default: module.Errors })))
const Changes = lazy(() => import('./pages/Changes').then((module) => ({ default: module.Changes })))
const Observability = lazy(() => import('./pages/Observability').then((module) => ({ default: module.Observability })))
const Knowledge = lazy(() => import('./pages/Knowledge').then((module) => ({ default: module.Knowledge })))
const Reports = lazy(() => import('./pages/Reports').then((module) => ({ default: module.Reports })))
const Audit = lazy(() => import('./pages/Audit').then((module) => ({ default: module.Audit })))
const Administration = lazy(() => import('./pages/Administration').then((module) => ({ default: module.Administration })))
const ApiReference = lazy(() => import('./pages/ApiReference').then((module) => ({ default: module.ApiReference })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      // Network blips (status 0, e.g. while a new revision starts) and server errors are retried with backoff.
      retry: (count, error) =>
        count < 3 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
      retryDelay: (attempt) => Math.min(600 * 2 ** attempt, 4000),
    },
    mutations: { retry: false },
  },
})

class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    if (this.state.failed) {
      return (
        <div className="connection-error">
          <div className="loading-brand">
            <BrandMark />
          </div>
          <EmptyState
            title="This workspace could not be displayed"
            description="Your persisted records have not been changed."
            action={
              <Button onClick={() => window.location.reload()}>
                Reload workspace
              </Button>
            }
          />
        </div>
      )
    }
    return this.props.children
  }
}

function ModuleWorkspace() {
  const location = useLocation()
  const module = navigation.find(
    (item) => location.pathname.startsWith(item.path) && item.path !== '/'
  )
  return (
    <>
      <PageHeader
        title={module?.label ?? 'Record not found'}
        description="Northstar Commerce / Synthetic workspace"
      />
      <EmptyState
        title="Workspace is being connected"
        description="This module has no active external integration."
        action={
          <Link className="button button-secondary" to="/">
            Return to command centre
          </Link>
        }
      />
    </>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <Tooltip.Provider delayDuration={250}>
          <BrowserRouter>
            <WorkspaceProvider>
              <Routes>
                <Route element={<Shell />}>
                  <Route index element={<Overview />} />
                  <Route path="incidents" element={<Incidents />} />
                  <Route path="incidents/:id" element={<IncidentDetail />} />
                  <Route path="war-room" element={<WarRoom />} />
                  <Route path="investigations" element={<Investigations />} />
                  <Route path="agents" element={<Agents />} />
                  <Route path="repositories" element={<Repositories />} />
                  <Route path="testing" element={<Testing />} />
                  <Route path="security" element={<Security />} />
                  <Route path="errors" element={<Errors />} />
                  <Route path="changes" element={<Changes />} />
                  <Route path="observability" element={<Observability />} />
                  <Route path="knowledge" element={<Knowledge />} />
                  <Route path="reports" element={<Reports />} />
                  <Route path="audit" element={<Audit />} />
                  <Route path="administration" element={<Administration />} />
                  <Route path="api-reference" element={<ApiReference />} />
                  <Route path="*" element={<ModuleWorkspace />} />
                </Route>
              </Routes>
              <WorkspaceDialogs />
            </WorkspaceProvider>
          </BrowserRouter>
        </Tooltip.Provider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

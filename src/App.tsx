import { Component } from 'react'
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
import { Overview } from './pages/Overview'
import { Incidents, IncidentDetail } from './pages/Incidents'
import { WorkspaceDialogs } from './components/Forms'
import { WarRoom } from './pages/WarRoom'
import { Investigations } from './pages/Investigations'
import { Agents } from './pages/Agents'
import { Repositories } from './pages/Repositories'
import { Testing } from './pages/Testing'
import { Security } from './pages/Security'
import { Changes } from './pages/Changes'
import { Observability } from './pages/Observability'
import { Knowledge } from './pages/Knowledge'
import { Reports } from './pages/Reports'
import { Audit } from './pages/Audit'
import { Administration } from './pages/Administration'
import { ApiError } from './lib/api'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: (count, error) =>
        count < 1 && (!(error instanceof ApiError) || error.status >= 500),
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
                  <Route path="changes" element={<Changes />} />
                  <Route path="observability" element={<Observability />} />
                  <Route path="knowledge" element={<Knowledge />} />
                  <Route path="reports" element={<Reports />} />
                  <Route path="audit" element={<Audit />} />
                  <Route path="administration" element={<Administration />} />
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

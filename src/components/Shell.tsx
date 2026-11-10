import { useEffect, useState } from 'react'
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from 'react-router-dom'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import {
  Activity,
  ArrowRight,
  Bell,
  BookOpen,
  Boxes,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ClipboardCheck,
  FileClock,
  FlaskConical,
  GitBranch,
  House,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  PanelLeftClose,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Telescope,
  TriangleAlert,
  Users,
  Workflow,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useWorkspace } from '../context'
import { dateTime, environments, errorMessage, roles } from '../lib/format'
import type { Environment } from '../types'
import {
  Avatar,
  Badge,
  BrandMark,
  Button,
  Drawer,
  EmptyState,
  IconButton,
  Modal,
  Notice,
  SearchInput,
} from './ui'

export const navigation: {
  path: string
  label: string
  icon: LucideIcon
  group: string
}[] = [
    {
      path: '/',
      label: 'Command centre',
      icon: LayoutDashboard,
      group: 'Operations',
    },
    {
      path: '/incidents',
      label: 'Issues & incidents',
      icon: TriangleAlert,
      group: 'Operations',
    },
    {
      path: '/war-room',
      label: 'AI War Room',
      icon: Network,
      group: 'Operations',
    },
    {
      path: '/investigations',
      label: 'Root cause analysis',
      icon: Telescope,
      group: 'Operations',
    },
    {
      path: '/agents',
      label: 'Agent orchestration',
      icon: Workflow,
      group: 'Operations',
    },
    {
      path: '/repositories',
      label: 'Project & repositories',
      icon: GitBranch,
      group: 'Engineering',
    },
    {
      path: '/testing',
      label: 'Testing & validation',
      icon: FlaskConical,
      group: 'Engineering',
    },
    {
      path: '/security',
      label: 'Security centre',
      icon: ShieldCheck,
      group: 'Engineering',
    },
    {
      path: '/changes',
      label: 'Change & release',
      icon: ClipboardCheck,
      group: 'Engineering',
    },
    {
      path: '/observability',
      label: 'Observability & logs',
      icon: Activity,
      group: 'Engineering',
    },
    {
      path: '/knowledge',
      label: 'Knowledge centre',
      icon: BookOpen,
      group: 'Governance',
    },
    {
      path: '/reports',
      label: 'Reports & analytics',
      icon: ChartNoAxesCombined,
      group: 'Governance',
    },
    {
      path: '/audit',
      label: 'Audit trail',
      icon: FileClock,
      group: 'Governance',
    },
    {
      path: '/administration',
      label: 'Administration',
      icon: Settings2,
      group: 'Governance',
    },
  ]

export function Shell() {
  const {
    data,
    session,
    environment,
    setEnvironment,
    selectIncident,
    switchRole,
    signOut,
    notify,
  } = useWorkspace()
  const routerNavigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [helpOpen, setHelpOpen] = useState(false)
  const [pendingEnvironment, setPendingEnvironment] =
    useState<Environment | null>(null)
  const [readNotifications, setReadNotifications] = useState<string[]>(() =>
    JSON.parse(localStorage.getItem('agentica-read-notifications') ?? '[]')
  )
  const [roleBusy, setRoleBusy] = useState(false)
  function navigate(path: string) {
    setMobileOpen(false)
    routerNavigate(path)
  }
  const currentPage = navigation.find((item) =>
    item.path === '/'
      ? location.pathname === '/'
      : location.pathname.startsWith(item.path)
  )
  const pending = data.approvals.filter(
    (approval) => approval.status === 'Pending'
  )
  const critical = data.incidents.filter(
    (incident) =>
      incident.severity === 'Critical' &&
      !['Closed', 'Resolved'].includes(incident.status)
  )
  const notifications = [
    ...pending.map((approval) => ({
      id: approval.id,
      title: approval.title,
      caption: 'Human approval required',
      path: '/changes',
      incident: approval.incidentId,
    })),
    ...critical.map((incident) => ({
      id: incident.id,
      title: incident.title,
      caption: `${incident.id} / ${incident.environment}`,
      path: `/incidents/${incident.id}`,
      incident: incident.id,
    })),
  ]
  const unread = notifications.filter(
    (notification) => !readNotifications.includes(notification.id)
  ).length
  const search = query.trim().toLowerCase()
  const results = [
    ...data.incidents.map((incident) => ({
      id: incident.id,
      title: incident.title,
      subtitle: `${incident.id} / ${incident.service} / ${incident.environment}`,
      path: `/incidents/${incident.id}`,
      icon: TriangleAlert,
      incident: incident.id,
    })),
    ...data.services.map((service) => ({
      id: service.id,
      title: service.name,
      subtitle: `${service.type} / ${service.health}`,
      path: `/war-room?service=${service.id}`,
      icon: Boxes,
      incident: '',
    })),
    ...data.knowledge.map((record) => ({
      id: record.id,
      title: record.title,
      subtitle: `${record.id} / ${record.type}`,
      path: `/knowledge?record=${record.id}`,
      icon: BookOpen,
      incident: record.incidents[0] ?? '',
    })),
    ...navigation.map((item) => ({
      id: item.path,
      title: item.label,
      subtitle: item.group,
      path: item.path,
      icon: item.icon,
      incident: '',
    })),
  ]
    .filter((item) =>
      `${item.title} ${item.subtitle}`.toLowerCase().includes(search)
    )
    .slice(0, 10)

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [])

  function markRead(ids: string[]) {
    const updated = [...new Set([...readNotifications, ...ids])]
    setReadNotifications(updated)
    localStorage.setItem('agentica-read-notifications', JSON.stringify(updated))
  }

  return (
    <div className={`app-shell ${collapsed ? 'nav-collapsed' : ''}`}>
      <a className="skip-link" href="#workspace-main">
        Skip to workspace
      </a>
      <header className="global-header">
        <div className="brand-area">
          <IconButton
            label="Toggle navigation"
            className="header-icon nav-toggle"
            onClick={() =>
              window.innerWidth < 1100
                ? setMobileOpen(!mobileOpen)
                : setCollapsed(!collapsed)
            }
          >
            <Menu size={21} />
          </IconButton>
          <Link to="/" className="brand" aria-label="BEHAVE KYNDRYL command centre">
            <BrandMark />
          </Link>
          <span className="brand-console">Command Centre</span>
        </div>
        <button className="global-search" onClick={() => setSearchOpen(true)}>
          <Search size={18} />
          <span>Search your workspace</span>
        </button>
        <div className="header-controls">
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <button className="workspace-switch">
                <Boxes size={16} />
                <span>Northstar Commerce</span>
                <ChevronDown size={14} />
              </button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content
                className="dropdown"
                sideOffset={10}
                align="end"
              >
                <Dropdown.Label>Current workspace</Dropdown.Label>
                <Dropdown.Item disabled>
                  <Check size={15} />
                  Northstar Commerce
                </Dropdown.Item>
                <Dropdown.Separator />
                <Dropdown.Item onSelect={() => navigate('/administration')}>
                  <Settings2 size={15} />
                  Workspace administration
                </Dropdown.Item>
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
          <label className="header-environment">
            <span className="environment-dot" />
            <span className="sr-only">Global environment</span>
            <select
              aria-label="Global environment"
              value={environment}
              onChange={(event) =>
                setPendingEnvironment(event.target.value as Environment)
              }
            >
              {environments.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <div className="header-divider" />
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <button
                className="header-icon notification-trigger"
                aria-label={`Notifications, ${unread} unread`}
              >
                <Bell size={20} />
                {unread > 0 && (
                  <span className="notification-count">{unread}</span>
                )}
              </button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content
                className="dropdown notification-menu"
                sideOffset={14}
                align="end"
              >
                <div className="dropdown-heading">
                  <strong>Notifications</strong>
                  <Badge dot={false}>{unread} new</Badge>
                </div>
                {notifications.length ? (
                  notifications.map((notification) => (
                    <Dropdown.Item
                      key={notification.id}
                      className="notification-item"
                      onSelect={() => {
                        markRead([notification.id])
                        selectIncident(notification.incident)
                        navigate(notification.path)
                      }}
                    >
                      <span
                        className={`notification-dot ${readNotifications.includes(notification.id) ? 'is-read' : ''}`}
                      />
                      <div>
                        <strong>{notification.title}</strong>
                        <small>{notification.caption}</small>
                      </div>
                      <ChevronRight size={14} />
                    </Dropdown.Item>
                  ))
                ) : (
                  <EmptyState title="No notifications" />
                )}
                <Dropdown.Separator />
                <Dropdown.Item
                  onSelect={() =>
                    markRead(
                      notifications.map((notification) => notification.id)
                    )
                  }
                >
                  <Check size={15} />
                  Mark all as read
                </Dropdown.Item>
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
          <IconButton
            label="Help and documentation"
            className="header-icon help-trigger"
            onClick={() => setHelpOpen(true)}
          >
            <CircleHelp size={20} />
          </IconButton>
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <button
                className="profile-trigger"
                aria-label={`Profile: ${session.user.name}`}
              >
                <Avatar name={session.user.name} />
                <ChevronDown size={13} />
              </button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content
                className="dropdown profile-menu"
                sideOffset={12}
                align="end"
              >
                <div className="profile-summary">
                  <Avatar name={session.user.name} />
                  <div>
                    <strong>{session.user.name}</strong>
                    <small>{session.user.role}</small>
                  </div>
                </div>
                <Dropdown.Separator />
                <Dropdown.Label>Demo identity</Dropdown.Label>
                {roles.map((role) => (
                  <Dropdown.Item
                    key={role}
                    disabled={roleBusy}
                    onSelect={async () => {
                      setRoleBusy(true)
                      try {
                        await switchRole(role)
                      } catch (error) {
                        notify(errorMessage(error), true)
                      } finally {
                        setRoleBusy(false)
                      }
                    }}
                  >
                    <span className="menu-check">
                      {role === session.user.role && <Check size={14} />}
                    </span>
                    {role}
                  </Dropdown.Item>
                ))}
                <Dropdown.Separator />
                <Dropdown.Item onSelect={() => navigate('/administration')}>
                  <Settings2 size={15} />
                  Settings & permissions
                </Dropdown.Item>
                <Dropdown.Item
                  onSelect={() => {
                    void signOut().catch((error) =>
                      notify(errorMessage(error), true)
                    )
                  }}
                >
                  <LogOut size={15} />
                  Sign out
                </Dropdown.Item>
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
        </div>
      </header>
      {mobileOpen && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={`sidebar ${mobileOpen ? 'mobile-open' : ''}`}
        aria-label="Main navigation"
      >
        <div className="sidebar-workspace">
          <div className="workspace-monogram">N</div>
          <div>
            <strong>Northstar</strong>
            <span>Commerce operations</span>
          </div>
          <IconButton
            label="Collapse navigation"
            onClick={() => {
              setCollapsed(!collapsed)
              setMobileOpen(false)
            }}
          >
            <PanelLeftClose size={16} />
          </IconButton>
        </div>
        <nav>
          {['Operations', 'Engineering', 'Governance'].map((group) => (
            <div className="nav-group" key={group}>
              <div className="nav-group-label">{group}</div>
              {navigation
                .filter((item) => item.group === group)
                .map((item) => (
                  <NavLink
                    key={item.path}
                    onClick={() => setMobileOpen(false)}
                    to={item.path}
                    end={item.path === '/'}
                    title={item.label}
                    className={({ isActive }) =>
                      `nav-item ${isActive ? 'active' : ''}`
                    }
                  >
                    <item.icon size={18} strokeWidth={1.7} />
                    <span>{item.label}</span>
                    {item.path === '/incidents' && (
                      <b className="nav-counter">
                        {
                          data.incidents.filter(
                            (incident) =>
                              !['Closed', 'Resolved'].includes(incident.status)
                          ).length
                        }
                      </b>
                    )}
                    {item.path === '/changes' && pending.length > 0 && (
                      <b className="nav-counter accent">{pending.length}</b>
                    )}
                  </NavLink>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="demo-source-icon">
            <FlaskConical size={18} />
          </div>
          <div>
            <strong>Demo workspace</strong>
            <span>Synthetic evidence source</span>
          </div>
          <span className="source-dot" />
        </div>
      </aside>
      <div className="workspace-frame">
        <div className="breadcrumb-bar">
          <div className="breadcrumbs">
            <Link to="/" aria-label="Command centre">
              <House size={14} />
            </Link>
            <ChevronRight size={12} />
            <span>Workspace</span>
            <ChevronRight size={12} />
            <strong>{currentPage?.label ?? 'Incident detail'}</strong>
          </div>
          <div className="snapshot-indicator">
            <span className="source-dot" />
            Synthetic snapshot<span className="breadcrumb-separator">/</span>
            <span>{dateTime(data.snapshotAt)}</span>
          </div>
        </div>
        <main
          id="workspace-main"
          className={`workspace-main ${location.pathname === '/war-room' ? 'war-room-main' : ''}`}
        >
          <Outlet />
        </main>
        <footer className="workspace-footer">
          <span>
            <ShieldCheck size={13} /> Human-governed operations
          </span>
          <span>
            BEHAVE KYNDRYL <span className="muted">/</span> Local demonstration{' '}
            <span className="version-label">v1.0</span>
          </span>
        </footer>
      </div>
      <Modal
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        title="Search workspace"
        description="Incidents, services, knowledge and modules"
      >
        <div className="command-search">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="Search by name, incident ID or service"
          />
          <div className="command-results">
            {results.map((result) => (
              <button
                key={`${result.path}-${result.id}`}
                onClick={() => {
                  if (result.incident) selectIncident(result.incident)
                  navigate(result.path)
                  setSearchOpen(false)
                  setQuery('')
                }}
              >
                <span className="command-icon">
                  <result.icon size={18} />
                </span>
                <span>
                  <strong>{result.title}</strong>
                  <small>{result.subtitle}</small>
                </span>
                <ArrowRight size={16} />
              </button>
            ))}
            {!results.length && (
              <EmptyState
                title="No matching results"
                description="No incident, service, document or module matches this query."
              />
            )}
          </div>
        </div>
      </Modal>
      <Modal
        open={Boolean(pendingEnvironment)}
        onClose={() => setPendingEnvironment(null)}
        title="Change environment view"
        description={`${environment} to ${pendingEnvironment ?? ''}`}
      >
        <div className="modal-body">
          <Notice title="Permissions remain unchanged">
            This changes the workspace filter, not execution authorization.
            Every action is checked against the selected incident's environment
            by the API.
          </Notice>
          <div className="environment-comparison">
            <Badge>{environment}</Badge>
            <ArrowRight size={20} />
            <Badge>{pendingEnvironment}</Badge>
          </div>
        </div>
        <div className="modal-footer">
          <Button onClick={() => setPendingEnvironment(null)}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => {
              if (pendingEnvironment) setEnvironment(pendingEnvironment)
              setPendingEnvironment(null)
            }}
          >
            Change view
          </Button>
        </div>
      </Modal>
      <Drawer
        open={helpOpen}
        onClose={() => setHelpOpen(false)}
        title="Workspace documentation"
        subtitle="BEHAVE KYNDRYL / Resources"
      >
        <Notice title="Local demonstration">
          Incident management, evidence storage and approval enforcement are
          connected to the local API. AI, scanner, repository and deployment
          providers are not connected.
        </Notice>
        <div className="resource-links">
          {data.knowledge
            .filter((record) => record.approved)
            .map((record) => (
              <button
                key={record.id}
                onClick={() => {
                  navigate(`/knowledge?record=${record.id}`)
                  setHelpOpen(false)
                }}
              >
                <BookOpen size={18} />
                <span>
                  <strong>{record.title}</strong>
                  <small>
                    {record.type} / v{record.version}
                  </small>
                </span>
                <ArrowRight size={16} />
              </button>
            ))}
          <a href="/api/docs" target="_blank" rel="noreferrer">
            <GitBranch size={18} />
            <span>
              <strong>API reference</strong>
              <small>Versioned API / OpenAPI</small>
            </span>
            <ArrowRight size={16} />
          </a>
          <button
            onClick={() => {
              navigate('/administration')
              setHelpOpen(false)
            }}
          >
            <Users size={18} />
            <span>
              <strong>Access & integration status</strong>
              <small>Role permissions and configured providers</small>
            </span>
            <ArrowRight size={16} />
          </button>
        </div>
        <div className="source-note">
          <Sparkles size={16} /> Model-generated analysis is never an
          authorization boundary.
        </div>
      </Drawer>
    </div>
  )
}

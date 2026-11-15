import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GitBranch, GitCommitHorizontal, LockKeyhole, Search } from 'lucide-react'
import { request } from '../lib/api'
import { errorMessage } from '../lib/format'
import { Badge, Button, Select } from './ui'

export interface PickedRepository {
  repo: string
  ref: string
  path: string
}

interface RepositoryRow {
  repo: string
  name: string
  description?: string
  language?: string
  private?: boolean
  defaultBranch?: string
  connected: boolean
  pullRequests: boolean
  ref?: string
  path?: string
}

const LATEST = ''

/**
 * Pick what a task reads from GitHub: a repository (connected ones first, or any public one by owner),
 * then a branch, a commit on it (or the latest) and a project folder. Read-only lookups.
 */
export function RepositoryPicker({ value, onChange }: { value: PickedRepository; onChange: (value: PickedRepository) => void }) {
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [branch, setBranch] = useState('')
  const [commit, setCommit] = useState(LATEST)
  const repo = value.repo
  const [owner, name] = repo.split('/')

  const repositories = useQuery({
    queryKey: ['github-repositories', search],
    queryFn: () => request<{ repositories: RepositoryRow[] }>(`/github/repositories?q=${encodeURIComponent(search)}`),
    staleTime: 60_000,
    retry: false,
  })
  const branches = useQuery({
    queryKey: ['github-branches', repo],
    queryFn: () => request<{ defaultBranch: string; private: boolean; branches: string[] }>(`/github/repositories/${owner}/${name}/branches`),
    enabled: Boolean(owner && name),
    staleTime: 60_000,
    retry: false,
  })
  const chosenBranch = branch || branches.data?.defaultBranch || ''
  const commits = useQuery({
    queryKey: ['github-commits', repo, chosenBranch],
    queryFn: () => request<{ commits: { sha: string; short: string; title: string; author: string; date: string }[] }>(`/github/repositories/${owner}/${name}/commits?ref=${encodeURIComponent(chosenBranch)}`),
    enabled: Boolean(owner && name && chosenBranch),
    staleTime: 60_000,
    retry: false,
  })
  const folders = useQuery({
    queryKey: ['github-folders', repo, chosenBranch],
    queryFn: () => request<{ folders: { path: string; markers: string[] }[]; truncated: boolean }>(`/github/repositories/${owner}/${name}/folders?ref=${encodeURIComponent(chosenBranch)}`),
    enabled: Boolean(owner && name && chosenBranch),
    staleTime: 60_000,
    retry: false,
  })

  // Keep the task's reference in step with what is picked: a commit pins the code, otherwise the branch.
  useEffect(() => {
    if (!repo) return
    const ref = commit || chosenBranch
    if (ref !== value.ref) onChange({ ...value, ref })
  }, [repo, commit, chosenBranch, value, onChange])

  // A monorepo with one obvious project folder: pick it.
  useEffect(() => {
    const found = folders.data?.folders ?? []
    if (repo && !value.path && found.length === 1 && found[0].path) onChange({ ...value, path: found[0].path })
  }, [folders.data, repo, value, onChange])

  function choose(row: RepositoryRow) {
    setBranch(row.ref || '')
    setCommit(LATEST)
    onChange({ repo: row.repo, ref: row.ref || '', path: row.path || '' })
  }

  const rows = repositories.data?.repositories ?? []
  const selected = rows.find((row) => row.repo === repo)
  return (
    <div className="repo-picker">
      {/* Not a <form>: this sits inside the task form, and forms cannot be nested. */}
      <div className="repo-picker-search">
        <input
          aria-label="GitHub owner or repository"
          placeholder="Owner (acme) or repository (acme/shop-api)"
          maxLength={140}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()  // Enter looks up, it does not create the task
              setSearch(query.trim())
            }
          }}
        />
        <Button busy={repositories.isFetching} onClick={() => setSearch(query.trim())}>
          <Search size={15} /> Find
        </Button>
      </div>
      {repositories.isError && <p className="repo-picker-error">{errorMessage(repositories.error)}</p>}
      <div className="repo-picker-list" role="listbox" aria-label="Repositories">
        {rows.length === 0 && !repositories.isFetching && (
          <p className="repo-picker-empty">{search ? 'No public repositories found.' : 'No connected repositories yet. Type an owner or owner/name to find a public one.'}</p>
        )}
        {rows.map((row) => (
          <button key={row.repo} type="button" role="option" aria-selected={row.repo === repo} className={`repo-picker-row ${row.repo === repo ? 'is-selected' : ''}`} onClick={() => choose(row)}>
            <span className="repo-picker-name">
              <GitBranch size={14} /> {row.repo}
              {row.connected && <Badge tone="outline">connected</Badge>}
              {row.private && <Badge tone="outline"><LockKeyhole size={10} /> private</Badge>}
              {row.pullRequests && <Badge tone="outline">pull requests on</Badge>}
            </span>
            {(row.description || row.language) && <span className="repo-picker-meta">{[row.language, row.description].filter(Boolean).join(' · ')}</span>}
          </button>
        ))}
      </div>
      {repo && (
        <div className="form-grid three">
          <label className="field-label">
            Branch
            <Select label="Branch" value={chosenBranch} onChange={(event) => { setBranch(event.target.value); setCommit(LATEST) }} disabled={!branches.data}>
              {(branches.data?.branches ?? (chosenBranch ? [chosenBranch] : [])).map((item) => (
                <option key={item} value={item}>{item}{item === branches.data?.defaultBranch ? ' (default)' : ''}</option>
              ))}
            </Select>
          </label>
          <label className="field-label">
            Commit
            <Select label="Commit" value={commit} onChange={(event) => setCommit(event.target.value)} disabled={!commits.data}>
              <option value={LATEST}>Latest on {chosenBranch || 'branch'}</option>
              {(commits.data?.commits ?? []).map((item) => (
                <option key={item.sha} value={item.sha}>{item.short} · {item.title}</option>
              ))}
            </Select>
          </label>
          <label className="field-label">
            Project folder
            <Select label="Project folder" value={value.path} onChange={(event) => onChange({ ...value, path: event.target.value })} disabled={!folders.data}>
              <option value="">Whole repository</option>
              {(folders.data?.folders ?? []).filter((item) => item.path).map((item) => (
                <option key={item.path} value={item.path}>{item.path} ({item.markers.join(', ')})</option>
              ))}
            </Select>
          </label>
        </div>
      )}
      {branches.isError && <p className="repo-picker-error">{errorMessage(branches.error)}</p>}
      {repo && (
        <p className="repo-picker-summary">
          <GitCommitHorizontal size={13} /> The agents will read <code>{repo}</code> at <code>{commit ? commit.slice(0, 7) : chosenBranch || '…'}</code>
          {value.path ? <> in <code>{value.path}/</code></> : null}, read-only.{' '}
          {selected?.connected
            ? selected.pullRequests
              ? 'An approved fix can become a pull request on a new branch.'
              : 'An approved fix is shown as a diff; this repository is not set up for pull requests.'
            : 'Public repository read without a token: an approved fix is shown as a diff, never pushed.'}
        </p>
      )}
    </div>
  )
}

import { expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { createServer } from 'node:net'
import { resolve } from 'node:path'

async function assertPortAvailable(port: number) {
  await new Promise<void>((complete, reject) => {
    const probe = createServer()
    probe.once('error', () => reject(new Error(`Test port ${port} is already in use. Existing processes were not changed.`)))
    probe.listen(port, '127.0.0.1', () => probe.close(() => complete()))
  })
}

async function stop(child: ChildProcess) {
  if (child.exitCode !== null || child.signalCode !== null) return
  await new Promise<void>(complete => {
    const deadline = setTimeout(() => { child.kill('SIGKILL'); complete() }, 2000)
    child.once('exit', () => { clearTimeout(deadline); complete() })
    child.kill('SIGTERM')
  })
}

export default async function globalSetup() {
  await assertPortAvailable(18001)
  await assertPortAvailable(15173)
  const python = resolve(process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
  const backend = spawn(python, ['-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '18001'], {
    stdio: 'ignore', windowsHide: true,
    env: { ...process.env, DATABASE_URL: 'sqlite:///:memory:', AGENTICA_MODE: 'demo', AGENTICA_DEMO_STEP_SECONDS: '1.2', AZURE_AI_PROJECT_ENDPOINT: '', AZURE_AI_MODEL_DEPLOYMENT: '', AZURE_OPENAI_ENDPOINT: '', AZURE_OPENAI_API_KEY: '', AZURE_CLIENT_SECRET: '' },
  })
  const frontend = spawn(process.execPath, [resolve('node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--port', '15173', '--strictPort'], {
    stdio: 'ignore', windowsHide: true, env: { ...process.env, AGENTICA_API_TARGET: 'http://127.0.0.1:18001' },
  })
  const cleanup = async () => { await Promise.all([stop(frontend), stop(backend)]) }
  backend.on('error', () => void cleanup())
  frontend.on('error', () => void cleanup())
  try {
    await expect.poll(async () => {
      try {
        const backendResponse = await fetch('http://127.0.0.1:18001/api/v1/health', { signal: AbortSignal.timeout(1500) })
        const frontendResponse = await fetch('http://127.0.0.1:15173/', { signal: AbortSignal.timeout(1500) })
        return backendResponse.ok && frontendResponse.ok
      } catch { return false }
    }, { timeout: 30_000, intervals: [100, 250, 500], message: 'Isolated test API and preview server must start' }).toBe(true)
  } catch (error) {
    await cleanup()
    throw error
  }
  return cleanup
}
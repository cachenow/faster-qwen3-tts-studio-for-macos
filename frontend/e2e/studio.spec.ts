import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { test, expect } from '@playwright/test'

let backend: ChildProcess
let directory: string
let url: string

test.beforeAll(async () => {
  directory = await mkdtemp(join(tmpdir(), 'studio-test-'))
  const workspace = fileURLToPath(new URL('../../', import.meta.url))
  const python = process.env.STUDIO_TEST_PYTHON || join(
    workspace, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python',
  )
  const args = ['-m', 'backend.main', '--mock', '--web', 'frontend/dist', '--root', directory]
  backend = spawn(python, args, {
    cwd: workspace,
    stdio: ['ignore', 'pipe', 'inherit'],
  })
  url = await new Promise<string>((resolve, reject) => {
    backend.once('error', reject)
    backend.once('exit', (code) => reject(new Error('Backend exited: ' + code)))
    backend.stdout?.once('data', (data: Buffer) => {
      const match = /^(\d+) /.exec(data.toString())
      if (match) resolve('http://127.0.0.1:' + match[1])
      else reject(new Error('Unexpected backend startup response'))
    })
  })
})

test.afterAll(async () => {
  if (backend && backend.exitCode === null) {
    const stopped = new Promise(resolve => backend.once('exit', resolve))
    backend.kill()
    await stopped
  }
  if (directory) await rm(directory, {recursive: true, force: true})
})

test('generates a mock clip, previews it and saves history', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('studio-language', 'en'))
  await page.goto(url)
  await expect(page.getByText('Development mock · test tone')).toBeVisible()
  await page.getByRole('textbox', {name: 'Script'}).fill('Studio preview')
  await page.getByRole('button', {name: 'Generate', exact: true}).click()
  await expect(page.getByRole('link', {name: 'Export WAV'})).toBeVisible()
  if (process.env.STUDIO_SCREENSHOT) await page.screenshot({path: process.env.STUDIO_SCREENSHOT})
  await page.getByRole('link', {name: 'History'}).click()
  await expect(page.getByText('Studio preview')).toBeVisible()
})

test('cancels an active generation and releases the worker', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('studio-language', 'en'))
  await page.goto(url)
  await page.getByRole('textbox', {name:'Script'}).fill('Long cancellation test. '.repeat(120))
  const connected = page.waitForResponse(response => response.url().includes('/tts/stream/') && response.ok())
  await page.getByRole('button', {name:'Generate', exact:true}).click()
  await connected
  await page.getByRole('button', {name:'Cancel generation'}).click()
  await expect.poll(async () => page.evaluate(async () => {
    const token = document.querySelector<HTMLMetaElement>('meta[name=studio-token]')?.content
    const response = await fetch('/api/v1/tasks', {headers:{Authorization:'Bearer ' + token}})
    return (await response.json()).length
  })).toBe(0)
  await expect(page.getByRole('link', {name:'Export WAV'})).toHaveCount(0)
})

test('runs a two-item batch and exports a ZIP', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('studio-language', 'en'))
  await page.goto(url)
  await page.getByRole('link', {name:'Batch'}).click()
  await page.getByRole('textbox', {name:'Paste one clip per line'}).fill('First clip\nSecond clip')
  await page.getByRole('button', {name:'Import text'}).click()
  await page.getByRole('button', {name:'Generate pending clips'}).click()
  const exportButton = page.getByRole('button', {name:'Export ZIP'})
  await expect(exportButton).toBeEnabled({timeout: 15000})
  const download = page.waitForEvent('download')
  await exportButton.click()
  expect((await download).suggestedFilename()).toBe('batch.zip')
})

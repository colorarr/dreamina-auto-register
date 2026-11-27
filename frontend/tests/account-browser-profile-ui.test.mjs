import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/pages/Accounts.tsx', import.meta.url), 'utf8')

test('account list has a dedicated registration browser profile column', () => {
  assert.match(source, /<TableHead>浏览器画像<\/TableHead>/)
  assert.match(source, /account\.registration_browser_profile/)
  assert.match(source, /account\.registration_browser_version/)
  assert.match(source, />未记录</)
})

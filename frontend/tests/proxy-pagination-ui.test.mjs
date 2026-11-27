import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('../src/pages/Proxies.tsx', import.meta.url), 'utf8')
const api = readFileSync(new URL('../src/services/api.ts', import.meta.url), 'utf8')

test('proxy page uses server pagination instead of rendering the full pool', () => {
  assert.match(page, /const pageSize = 100/)
  assert.match(page, /page_size: pageSize/)
  assert.match(page, /共 \{total\} 条/)
  assert.match(api, /ProxyListResponse/)
  assert.match(api, /\/proxies\?\$\{query\}/)
})

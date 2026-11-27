import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/pages/OutlookMailboxes.tsx', import.meta.url), 'utf8')

test('import dialog uses semantic theme colors', () => {
  const dialog = source.slice(source.indexOf('<Dialog open='), source.indexOf('</Dialog>', source.indexOf('<Dialog open=')))
  assert.doesNotMatch(dialog, /bg-\[#|bg-white\/\[|border-white\//)
  assert.match(dialog, /bg-card|bg-background/)
  assert.match(dialog, /border-border|border-input/)
})

test('import dialog supports Outlook and generic API formats', () => {
  assert.match(source, /generic_api/)
  assert.match(source, /邮箱----取码地址/)
  assert.match(source, /provider_type/)
})

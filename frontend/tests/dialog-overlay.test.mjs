import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/ui/dialog.tsx', import.meta.url), 'utf8')

test('dialog overlay is lighter by day and stronger by night', () => {
  assert.doesNotMatch(source, /bg-black\/80/)
  assert.match(source, /bg-black\/20/)
  assert.match(source, /dark:bg-black\/50/)
})

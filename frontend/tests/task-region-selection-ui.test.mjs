import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/tasks/CreateTaskModal.tsx', import.meta.url), 'utf8')

test('task creation never defaults proxy country to the first region', () => {
  assert.doesNotMatch(source, /regions\[0\]/)
  assert.match(source, /proxy_region:\s*regions\.includes\(current\.proxy_region\)\s*\?\s*current\.proxy_region\s*:\s*''/)
  assert.match(source, /disabled=\{!formData\.proxy_region \|\| regionsLoading\}/)
})

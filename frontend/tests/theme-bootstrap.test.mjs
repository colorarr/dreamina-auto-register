import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import test from 'node:test'

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
function bootstrap(value, blocked = false) {
    const script = html.match(/<script id="theme-bootstrap">([\s\S]*?)<\/script>/)?.[1]
    assert.ok(script, '首屏主题脚本缺失')
    const root = { classList: { toggle(name, active) { assert.equal(name, 'dark'); root.dark = active } } }
    runInNewContext(script, {
        document: { documentElement: root },
        localStorage: { getItem(key) {
            assert.equal(key, 'app_theme')
            if (blocked) throw new Error('blocked')
            return value
        } },
    })
    return root.dark
}

for (const [name, value, expected, blocked] of [
    ['default is night', null, true],
    ['restores day', 'light', false],
    ['restores night', 'dark', true],
    ['ignores invalid preference', 'invalid', true],
    ['storage unavailable defaults to night', null, true, true],
]) {
    test(name, () => assert.equal(bootstrap(value, blocked), expected))
}

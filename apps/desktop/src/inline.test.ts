import assert from 'node:assert/strict'
import { test } from 'node:test'

import { inlineParts } from './inline.ts'

const text = (t: string) => ({ kind: 'text', text: t })

test('underscores inside a word stay as written', () => {
  for (const s of ['data_master_md', '__init__.py', '__init__', '_private_var_', '_foo_bar_', 'https://x.com/a_b_c']) {
    assert.deepEqual(inlineParts(s), [text(s)], s)
  }
})

test('italics still work at word boundaries', () => {
  assert.deepEqual(inlineParts('see _this one_ here'), [text('see '), { kind: 'italic', text: 'this one' }, text(' here')])
  assert.deepEqual(inlineParts('(_paren_)'), [text('('), { kind: 'italic', text: 'paren' }, text(')')])
  assert.deepEqual(inlineParts('_a_ and snake_case_name'), [{ kind: 'italic', text: 'a' }, text(' and snake_case_name')])
})

test('bold and code still work', () => {
  assert.deepEqual(inlineParts('**big** and `a_b_c`'), [{ kind: 'bold', text: 'big' }, text(' and '), { kind: 'code', text: 'a_b_c' }])
})

test('unmatched markers keep every character', () => {
  for (const s of ['**foo', '`foo', '_foo', '**']) assert.deepEqual(inlineParts(s), [text(s)], s)
})

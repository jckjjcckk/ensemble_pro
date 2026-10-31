// "Remembered from page N" in the reader's questions (011). Run: npm test (node --test, types stripped).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { layoutFor, layoutLabels, rememberedLine } from '../src/app/remembered.ts'

test('a remembered instrument names the page and whose word it was', () => {
  assert.equal(rememberedLine([{ instrument: 'Violino I', page: 2, source: 'human', how: 'label', label: 'Viol. I' }]), 'Violino I, remembered from page 2 (your answer)')
  assert.equal(rememberedLine([{ instrument: 'Violino I', page: 1, source: 'model', how: 'label', label: 'Viol. I' },
    { instrument: 'Violoncello', page: 3, source: 'model', how: 'layout' }]), 'Violino I, remembered from page 1 (“Viol. I” read there); Violoncello, remembered from page 3')
  assert.equal(rememberedLine(undefined), '')
})

test('a layout is offered only for its own staff count, and labels each staff', () => {
  const lay = { staves: 3, parts: ['Violin', 'Piano'], staves_per_part: [1, 2], page: 2, source: 'human' as const }
  assert.equal(layoutFor([lay], 4), null)
  assert.equal(layoutFor([{ ...lay, staves_per_part: [1, 1] }], 3), null)
  assert.deepEqual(layoutLabels(layoutFor([lay], 3)!), ['Violin', 'Piano', 'Piano'])
})

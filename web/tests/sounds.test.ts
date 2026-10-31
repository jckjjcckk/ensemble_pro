// Where Play the parts finds its samples, and when a fetch of one has arrived (`sounds.ts`). Run: npm test.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { SAMPLES, fetchFault, sampleArrived, samplePath, sampleUrl, voiceFor } from '../src/app/sounds.ts'

test('in the iPad shell a sample resolves on capacitor://localhost, from any route', () => {
  assert.equal(sampleUrl('piano', 'Fs4', '/', 'capacitor://localhost/'), 'capacitor://localhost/sounds/piano/Fs4.mp3')
  assert.equal(sampleUrl('strings', 'cello-C2', '/', 'capacitor://localhost/score/4d73bdc5?bar=12#stand'), 'capacitor://localhost/sounds/strings/cello-C2.mp3')
})

test('the hosted app and the dev server resolve on their own origin', () => {
  assert.equal(sampleUrl('strings', 'violin-E4', '/', 'https://folio-app.jckjjcckk.com/score/abc'), 'https://folio-app.jckjjcckk.com/sounds/strings/violin-E4.mp3')
  assert.equal(sampleUrl('piano', 'C4', '/', 'http://192.168.1.20:5173/'), 'http://192.168.1.20:5173/sounds/piano/C4.mp3')
})

test('a base other than the root is kept, with or without its slash', () => {
  assert.equal(sampleUrl('piano', 'C4', '/folio/', 'https://example.com/folio/score/1'), 'https://example.com/folio/sounds/piano/C4.mp3')
  assert.equal(sampleUrl('piano', 'C4', '/folio', 'https://example.com/folio/score/1'), 'https://example.com/folio/sounds/piano/C4.mp3')
})

test('every note maps to an mp3 under its voice', () => {
  for (const [voice, notes] of Object.entries(SAMPLES) as [keyof typeof SAMPLES, Record<string, string>][]) {
    for (const stem of Object.values(notes)) assert.match(samplePath(voice, stem), new RegExp(`^sounds/${voice}/[\\w-]+\\.mp3$`))
  }
})

test('a bundled mp3 in WKWebView (status 0, the whole file) has arrived; nothing or an HTTP error has not', () => {
  assert.equal(sampleArrived(0, 93306), true)        // Capacitor's media answer, as measured on the simulator
  assert.equal(sampleArrived(200, 93306), true)
  assert.equal(sampleArrived(0, 0), false)
  assert.equal(sampleArrived(200, 0), false)
  assert.equal(sampleArrived(404, 512), false)
  assert.equal(fetchFault(404, 512), 'HTTP 404')
  assert.equal(fetchFault(0, 0), 'no data')
  assert.equal(fetchFault(200, 0), 'an empty file')
})

test('parts take the piano or the strings', () => {
  assert.equal(voiceFor('Piano'), 'piano')
  assert.equal(voiceFor('Violin I'), 'strings')
  assert.equal(voiceFor('Violoncello'), 'strings')
  assert.equal(voiceFor('Part 1'), 'piano')
})

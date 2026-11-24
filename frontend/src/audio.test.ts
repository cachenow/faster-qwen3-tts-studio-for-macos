import { expect, test } from 'vitest'
import { decodePcm } from './audio'

test('decodes signed little-endian PCM16', () => {
  expect(Array.from(decodePcm(btoa('\0\x80\0\0\0\x40')))).toEqual([-1, 0, 0.5])
  expect(() => decodePcm(btoa('\0'))).toThrow()
})

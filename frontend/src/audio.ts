export function decodePcm(encoded: string): Float32Array<ArrayBuffer> {
  const binary = atob(encoded)
  if (binary.length % 2) throw new Error('Invalid PCM chunk')
  const bytes = Uint8Array.from(binary, (byte) => byte.charCodeAt(0))
  const view = new DataView(bytes.buffer)
  const result = new Float32Array(bytes.length / 2)
  for (let i = 0; i < result.length; i++) result[i] = view.getInt16(i * 2, true) / 32768
  return result
}

export class Preview {
  private context = new AudioContext()
  private next = 0

  async start() { await this.context.resume() }
  async toggle() {
    if (this.context.state === 'suspended') await this.context.resume()
    else await this.context.suspend()
  }
  append(rate: number, encoded: string) {
    const pcm = decodePcm(encoded)
    const buffer = this.context.createBuffer(1, pcm.length, rate)
    buffer.copyToChannel(pcm, 0)
    const source = this.context.createBufferSource()
    source.buffer = buffer
    source.connect(this.context.destination)
    const start = Math.max(this.next, this.context.currentTime + 0.08)
    source.start(start)
    this.next = start + buffer.duration
  }
  close() { return this.context.close() }
}

export async function recordedWav(blob: Blob, start = 0, end?: number) {
  const context = new AudioContext()
  try {
    const audio = await context.decodeAudioData(await blob.arrayBuffer())
    const channels = Array.from({length: audio.numberOfChannels}, (_, i) => audio.getChannelData(i))
    const first = Math.max(0, Math.floor(start * audio.sampleRate))
    const last = Math.min(audio.length, Math.ceil((end ?? audio.duration) * audio.sampleRate))
    const samples = last - first
    if (samples <= 0) throw new Error('Select a valid audio range')
    const bytes = new ArrayBuffer(44 + samples * 2)
    const view = new DataView(bytes)
    const ascii = (offset: number, value: string) =>
      Array.from(value).forEach((letter, i) => view.setUint8(offset + i, letter.charCodeAt(0)))
    ascii(0, 'RIFF')
    view.setUint32(4, bytes.byteLength - 8, true)
    ascii(8, 'WAVEfmt ')
    view.setUint32(16, 16, true)
    view.setUint16(20, 1, true)
    view.setUint16(22, 1, true)
    view.setUint32(24, audio.sampleRate, true)
    view.setUint32(28, audio.sampleRate * 2, true)
    view.setUint16(32, 2, true)
    view.setUint16(34, 16, true)
    ascii(36, 'data')
    view.setUint32(40, samples * 2, true)
    for (let i = 0; i < samples; i++) {
      const sample = channels.reduce((sum, channel) => sum + channel[first + i], 0) / channels.length
      view.setInt16(44 + i * 2, Math.round(Math.min(1, Math.max(-1, sample)) * 32767), true)
    }
    return new File([bytes], 'microphone.wav', {type:'audio/wav'})
  } finally { await context.close() }
}

/**
 * Decode a raw audio Blob and re-encode as 16kHz mono WAV.
 * Uses the Web Audio API's decodeAudioData for format-agnostic decoding,
 * then writes a standard PCM WAV header for server compatibility.
 */
export async function encodeToWav(
  blob: Blob,
  targetSampleRate = 16_000,
): Promise<Blob> {
  // Decode with a throw-away context to get duration, then resample via OfflineAudioContext
  const arrayBuffer = await blob.arrayBuffer();
  const probe = new OfflineAudioContext(1, 1, targetSampleRate);
  const decoded = await probe.decodeAudioData(arrayBuffer);

  // Mixdown to mono and resample
  const mono = new OfflineAudioContext(
    1,
    Math.ceil(decoded.duration * targetSampleRate),
    targetSampleRate,
  );
  const src = mono.createBufferSource();
  src.buffer = decoded;
  src.connect(mono.destination);
  src.start(0);
  const rendered = await mono.startRendering();

  return pcmToWav(rendered.getChannelData(0), targetSampleRate);
}

function pcmToWav(samples: Float32Array, sampleRate: number): Blob {
  const numSamples = samples.length;
  const bytesPerSample = 2; // 16-bit PCM
  const blockAlign = bytesPerSample; // mono
  const byteRate = sampleRate * blockAlign;
  const dataBytes = numSamples * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);        // PCM chunk size
  view.setUint16(20, 1, true);         // PCM format
  view.setUint16(22, 1, true);         // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);        // bits per sample
  writeString(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  // Convert Float32 PCM [-1, 1] to Int16
  let offset = 44;
  for (let i = 0; i < numSamples; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }

  return new Blob([buffer], { type: "audio/wav" });
}

function writeString(view: DataView, offset: number, value: string): void {
  for (let i = 0; i < value.length; i++) {
    view.setUint8(offset + i, value.charCodeAt(i));
  }
}

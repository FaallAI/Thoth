// Generates python/tests/fixtures/assembly/classifier_parity.json from Scout's classifier.
// Run once from the repository root: bun python/tests/assembly/scout_classifier_parity.ts
// Re-run only if scout/lib/subtitle_vision.ts changes (it is frozen while Scout retires).
import fs from 'node:fs';
import path from 'node:path';
import {
  buildSampleTimes,
  classifyOcrFrames,
  type OcrBox,
  type OcrFrame,
} from '../../../scout/lib/subtitle_vision.ts';

const b = (text: string, x0: number, y0: number, x1: number, y1: number): OcrBox => ({
  text, x0, y0, x1, y1,
});
const f = (t: number, ...boxes: OcrBox[]): OcrFrame => ({ t, boxes });
const banner = (t: number, y1: number) => f(t, b('IDN TIMES', 0.25, 0.8, 0.75, y1));

// Verbatim inputs of every classifyOcrFrames call in scout/lib/subtitle_vision.test.ts.
const HAND: { name: string; frames: OcrFrame[]; duration: number }[] = [
  { name: 'cjk_captions', duration: 8, frames: [
    f(1, b('啊', 0.18, 0.72, 0.82, 0.8)), f(3, b('呢', 0.18, 0.72, 0.82, 0.8)),
    f(5, b('哦', 0.18, 0.72, 0.82, 0.8))] },
  { name: 'phantom_ocr', duration: 110, frames: [
    f(0.5, b('三', 0, 0.77, 0.424, 0.84)), f(1, b('1', 0, 0.75, 0.499, 0.808)),
    f(2, b('#', 0, 0.64, 0.66, 0.712)), f(3, b('#', 0, 0.75, 0.65, 0.844)),
    f(4, b('#', 0, 0.8, 0.6, 0.884)), f(5, b('#', 0.12, 0.777, 0.76, 0.852)),
    f(64.733334, b('福', 0, 0, 0.997, 0.997)), f(84.644445, b('福', 0, 0, 0.996, 0.996)),
    f(104.555556, b('1', 0, 0, 0.995, 0.999))] },
  { name: 'hybrid', duration: 26.935, frames: [
    f(0.5, b('CUCURELLA BUNGKUS TROFI', 0.05, 0.46, 0.82, 0.54)),
    f(1, b('CUCURELLA BUNGKUS TROFI', 0.05, 0.46, 0.82, 0.54)),
    f(3, b('CUCURELLA BUNGKUS TROFI', 0.05, 0.46, 0.82, 0.54)),
    f(5, b('BAWA PULANG', 0.25, 0.78, 0.75, 0.85)),
    f(8, b('KOK PIALA SEMEWAH', 0.18, 0.76, 0.82, 0.86)),
    f(12, b('REPLIKA RESMI YANG', 0.2, 0.75, 0.8, 0.86))] },
  { name: 'intro_then_moving_track', duration: 10, frames: [
    f(0.5, b('INTRO HEADLINE', 0.08, 0.4, 0.92, 0.52)),
    f(2, b('INTRO HEADLINE', 0.06, 0.39, 0.94, 0.53)),
    f(4, b('spoken one', 0.24, 0.74, 0.7, 0.8)),
    f(6, b('spoken two', 0.12, 0.72, 0.88, 0.84))] },
  { name: 'partial_failure', duration: 8, frames: [
    f(1, b('MATCH DAY', 0.1, 0.3, 0.9, 0.4)), f(2, b('MATCH DAY', 0.1, 0.3, 0.9, 0.4)),
    { t: 3, boxes: [], error: 'TimeoutError' }, f(4, b('MATCH DAY', 0.1, 0.3, 0.9, 0.4)),
    f(5)] },
  { name: 'real_geometry', duration: 10, frames: [
    f(1, b('CURELLA BUNGKUS TROFI', 0.09, 0.521, 0.803, 0.546),
      b('PIALA DUNIA PAKE KRESEK', 0.09, 0.568, 0.777, 0.595)),
    f(2, b('CUCURELLA BUNGKUS TROFI', 0.114, 0.521, 0.924, 0.546),
      b('PIALA DUNIA PAKE KRESEK', 0.114, 0.568, 0.894, 0.593)),
    f(3, b('CUCURELLA BUNGKUS TROFI', 0.117, 0.521, 0.919, 0.546),
      b('PIALA DUNIA PAKE KRESEK', 0.117, 0.567, 0.891, 0.592)),
    f(4, b('DIA NGGAK TAHU', 0.174, 0.758, 0.83, 0.799)),
    f(5, b('BAWA PULANG', 0.215, 0.755, 0.787, 0.799)),
    f(8, b('KOK PIALA SEMEWAH', 0.277, 0.733, 0.7, 0.824))] },
  { name: 'lower_third', duration: 8, frames: [
    f(1, b('LIVE NEWS', 0.02, 0.84, 0.14, 0.89), b('BREAKING NEWS', 0.18, 0.84, 0.7, 0.89)),
    f(3, b('LIVE NEWS', 0.02, 0.84, 0.14, 0.89), b('MARKETS RALLY', 0.182, 0.84, 0.66, 0.89)),
    f(5, b('LIVE NEWS', 0.02, 0.84, 0.14, 0.89), b('MORE AT TEN', 0.181, 0.84, 0.62, 0.89))] },
  { name: 'left_captions', duration: 8, frames: [
    f(1, b('I SAW IT LIVE', 0.05, 0.72, 0.55, 0.79)),
    f(3, b('THIS TO HAPPEN', 0.052, 0.72, 0.52, 0.79)),
    f(5, b('WATCH UNTIL END', 0.051, 0.72, 0.58, 0.79))] },
  { name: 'stable_two_line', duration: 8, frames: [
    f(1, b('THIS LINE STAYS', 0.18, 0.7, 0.82, 0.75), b('SO DOES THIS', 0.25, 0.76, 0.75, 0.81)),
    f(3, b('THIS LINE STAYS', 0.18, 0.7, 0.82, 0.75), b('SO DOES THIS', 0.25, 0.76, 0.75, 0.81)),
    f(5, b('THIS LINE STAYS', 0.18, 0.7, 0.82, 0.75), b('SO DOES THIS', 0.25, 0.76, 0.75, 0.81))] },
  { name: 'watermark', duration: 10, frames: [
    f(1, b('@channel', 0.86, 0.03, 0.98, 0.06)), f(3, b('@channel', 0.86, 0.03, 0.98, 0.06)),
    f(8, b('@channel', 0.86, 0.03, 0.98, 0.06))] },
  { name: 'banner_jitter', duration: 20, frames: [
    banner(1, 0.8384), banner(2, 0.8404), banner(3, 0.8384), banner(4, 0.8404),
    banner(5, 0.8384)] },
  { name: 'real_cover', duration: 20, frames: [
    f(1, b('BREAKING STORY HEADLINE', 0.2, 0.3, 0.8, 0.42)),
    f(3, b('BREAKING STORY HEADLINE', 0.2, 0.3, 0.8, 0.42)), f(5)] },
  { name: 'cover', duration: 12, frames: [
    f(0.5, b('MATCH DAY', 0.1, 0.3, 0.9, 0.43)), f(2, b('MATCH DAY', 0.11, 0.3, 0.91, 0.43)),
    f(4), f(8)] },
  { name: 'subtitle_moving', duration: 10, frames: [
    f(1), f(3, b('SATU', 0.16, 0.73, 0.7, 0.8)), f(5, b('DUA', 0.25, 0.75, 0.85, 0.84)),
    f(8, b('TIGA', 0.1, 0.72, 0.74, 0.81))] },
  { name: 'separate_tracks', duration: 8, frames: [
    f(1), f(3, b('LEFT CAPTION', 0.05, 0.72, 0.35, 0.8)),
    f(5, b('RIGHT CAPTION', 0.65, 0.72, 0.95, 0.8))] },
  { name: 'simultaneous_tracks', duration: 8, frames: [
    f(1), f(3, b('LEFT ONE', 0.05, 0.72, 0.35, 0.8), b('RIGHT ONE', 0.65, 0.72, 0.95, 0.8)),
    f(5, b('LEFT TWO', 0.06, 0.72, 0.36, 0.8), b('RIGHT TWO', 0.64, 0.72, 0.94, 0.8))] },
  { name: 'split_transition', duration: 8, frames: [
    f(1), f(3, b('BROAD CAPTION', 0.2, 0.72, 0.8, 0.8)),
    f(5, b('LEFT SPLIT', 0.1, 0.72, 0.4, 0.8), b('RIGHT SPLIT', 0.6, 0.72, 0.9, 0.8))] },
  { name: 'two_line', duration: 8, frames: [
    f(1), f(3, b('BARIS SATU', 0.16, 0.7, 0.82, 0.76), b('BARIS DUA', 0.22, 0.77, 0.76, 0.84)),
    f(5, b('KALIMAT BARU', 0.14, 0.71, 0.8, 0.77), b('LANJUTANNYA', 0.2, 0.78, 0.78, 0.85))] },
  { name: 'headline_then_captions', duration: 9, frames: [
    f(1, b('HEADLINE', 0.1, 0.3, 0.9, 0.4)), f(2, b('HEADLINE', 0.1, 0.3, 0.9, 0.4)), f(3),
    f(5, b('CAPTION A', 0.2, 0.72, 0.8, 0.8)), f(7, b('CAPTION B', 0.2, 0.72, 0.8, 0.8))] },
  { name: 'repeated_merge', duration: 6, frames: [
    f(1, b('ONE', 0.2, 0.72, 0.8, 0.8)), f(2, b('TWO', 0.2, 0.72, 0.8, 0.8)),
    f(3, b('THREE', 0.2, 0.72, 0.8, 0.8)), f(4, b('FOUR', 0.2, 0.72, 0.8, 0.8)),
    f(5, b('FIVE', 0.2, 0.72, 0.8, 0.8))] },
];

// mulberry32: a tiny seeded generator so the fixture is reproducible.
function rng(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const WORDS = ['GEMPA', 'WARGA', 'banjir', 'LIVE NEWS', 'BREAKING NEWS', 'kata', 'PIALA',
  'jalan', 'RUMAH', 'akhirnya', 'netizen', '@akun', '2026', 'BERITA', 'SATU', 'DUA'];

function randomCase(index: number) {
  const r = rng(1000 + index);
  const pick = <T>(items: T[]) => items[Math.floor(r() * items.length)];
  const jit = (v: number) => Math.min(1, Math.max(0, v + (r() - 0.5) * 0.02));
  const duration = Number((3 + r() * 117).toFixed(3));
  const times = buildSampleTimes(duration, 12);
  const headline = r() < 0.5 ? pick(WORDS) + ' ' + pick(WORDS) + ' ' + pick(WORDS) : null;
  const headlineUntil = 1 + r() * 5;
  const subtitles = r() < 0.5;
  const subY = 0.68 + r() * 0.15;
  const chyron = r() < 0.25;
  const watermark = r() < 0.4;
  const frames: OcrFrame[] = times.map((t) => {
    if (r() < 0.04) return { t, boxes: [], error: 'frame_extract' };
    const boxes: OcrBox[] = [];
    if (headline && t <= headlineUntil) boxes.push(b(headline, jit(0.08), jit(0.3), jit(0.9), jit(0.36)));
    if (subtitles && t > headlineUntil && r() < 0.85) {
      const x0 = jit(0.12 + r() * 0.1);
      boxes.push(b(pick(WORDS) + ' ' + pick(WORDS), x0, jit(subY), Math.min(1, x0 + 0.4 + r() * 0.4), jit(subY + 0.05)));
      if (r() < 0.3) boxes.push(b(pick(WORDS), jit(0.2), jit(subY + 0.06), jit(0.75), jit(subY + 0.11)));
    }
    if (chyron) {
      boxes.push(b('LIVE NEWS', 0.02, 0.84, 0.14, 0.89));
      boxes.push(b(pick(WORDS) + ' ' + pick(WORDS), jit(0.18), 0.84, jit(0.7), 0.89));
    }
    if (watermark) boxes.push(b('@channel', 0.86, 0.03, 0.98, 0.06));
    if (r() < 0.15) boxes.push(b(pick(WORDS), r() * 0.8, r() * 0.9, r() * 0.2 + 0.8, r() * 0.1 + 0.9));
    return { t, boxes };
  });
  return { name: `random_${index}`, frames, duration };
}

const cases = [...HAND, ...Array.from({ length: 300 }, (_, i) => randomCase(i))].map((c) => ({
  ...c,
  verdict: classifyOcrFrames(c.frames, c.duration),
}));
const sampleTimes = [0, 0.3, 0.5, 0.6, 3, 5, 5.2, 7, 12, 30, 59.94, 90, 600].flatMap((duration) =>
  [1, 6, 12, 20].map((maxFrames) => ({ duration, maxFrames, times: buildSampleTimes(duration, maxFrames) })),
);
const out = path.join(import.meta.dirname, '..', 'fixtures', 'assembly', 'classifier_parity.json');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify({ source: 'scout/lib/subtitle_vision.ts', cases, sampleTimes }) + '\n');
console.log(`wrote ${cases.length} cases and ${sampleTimes.length} sample-time cases`);

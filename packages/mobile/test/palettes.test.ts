import { describe, expect, it } from 'vitest';
import { blockBackground, blocks, brand, ink, paper, type Palette } from '@tenmina/tokens';

/* WCAG 2.x contrast of two opaque #RRGGBB colours. */
function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
function contrast(a: string, b: string): number {
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/* Every place text sits: the palette it draws with and the colour under it. */
const cases: [string, Palette, string][] = [
  ['white screen', paper, paper.ground],
  ['white screen, panel', paper, paper.surface],
  ['black screen', ink, ink.ground],
  ['black screen, panel', ink, ink.surface],
  ['black strip on a white screen', blocks.raisedOnPaper, blockBackground('raised', false)],
  ['black strip on a black screen', blocks.raisedOnInk, blockBackground('raised', true)],
  ['lime block', blocks.lime, blockBackground('lime', false)],
  ['orange block', blocks.orange, blockBackground('orange', false)],
  ['Amber block', blocks.amber, blockBackground('amber', false)],
  ['red block', blocks.red, blockBackground('red', false)],
  ['ticket on a black screen', blocks.ticket, brand.paper],
];

describe('Bloc palettes: text never takes the colour of its ground', () => {
  it.each(cases)('%s: text and muted text reach 4.5:1', (_, p, bg) => {
    expect(contrast(p.text, bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(p.textMuted, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it('the black strip stays dark in dark mode, so lime and orange stay legible on it', () => {
    const bg = blockBackground('raised', true);
    expect(contrast(brand.lime, bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(brand.orange, bg)).toBeGreaterThanOrEqual(4.5);
    expect(bg).not.toBe(ink.ground);
  });

  it('red as text for an unmatched payee name reaches 4.5:1 on both grounds and their panels', () => {
    for (const [p, bg] of [[paper, paper.ground], [paper, paper.surface], [ink, ink.ground], [ink, ink.surface]] as const) {
      expect(contrast(p.redText, bg)).toBeGreaterThanOrEqual(4.5);
    }
  });
});

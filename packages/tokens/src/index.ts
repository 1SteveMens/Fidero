// Fidero app design tokens, version 2 (November 2026).
// A current, native-feeling direction: platform chrome (Liquid Glass on iOS,
// Material 3 on Android) with Fidero's own layer on top: an indigo hero,
// borderless cards with soft depth, large type and generous radii.
// Light and dark share keys so components never pick a literal colour.

export const light = {
  bg: '#F5F3EE',
  surface: '#FFFFFF',
  surfaceAlt: '#EEEAE2',
  text: '#16161A',
  textMuted: '#5F5B55',
  separator: 'rgba(22, 22, 26, 0.08)',
  primary: '#3346B8',
  onPrimary: '#FFFFFF',
  primarySoft: '#E6E9FB',
  accent: '#C2562A',
  success: '#0B7A57',
  successSoft: '#DDF3EA',
  warning: '#8A5200',
  warningSoft: '#FCEFD2',
  danger: '#B3261E',
  dangerSoft: '#FBE5E3',
  shadow: 'rgba(22, 22, 26, 0.10)',
} as const;

export type Palette = { [K in keyof typeof light]: string };

export const dark: Palette = {
  bg: '#0D0E11',
  surface: '#17191E',
  surfaceAlt: '#22252C',
  text: '#F2F1EE',
  textMuted: '#A7A39C',
  separator: 'rgba(255, 255, 255, 0.08)',
  primary: '#8E9DFF',
  onPrimary: '#0D0E11',
  primarySoft: '#1E2447',
  accent: '#F08A5D',
  success: '#5AD1A1',
  successSoft: '#0F2B22',
  warning: '#F5C26B',
  warningSoft: '#2E2410',
  danger: '#FF8A80',
  dangerSoft: '#351614',
  shadow: 'rgba(0, 0, 0, 0)',
};

/** The hero surface stays deep indigo in both themes; text on it is always white. */
export const hero = {
  from: '#2E3EB0',
  to: '#141C55',
  text: '#FFFFFF',
  textMuted: 'rgba(255, 255, 255, 0.72)',
  chip: 'rgba(255, 255, 255, 0.14)',
} as const;

export const space = { 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 7: 32, 8: 40 } as const;

export const radius = { sm: 10, md: 14, lg: 20, xl: 28, pill: 999 } as const;

/** Type scale close to the iOS and Material 3 defaults. */
export const type = {
  largeTitle: { fontSize: 34, lineHeight: 41, fontWeight: '700' },
  title: { fontSize: 22, lineHeight: 28, fontWeight: '700' },
  headline: { fontSize: 17, lineHeight: 22, fontWeight: '600' },
  body: { fontSize: 17, lineHeight: 24, fontWeight: '400' },
  callout: { fontSize: 15, lineHeight: 20, fontWeight: '400' },
  footnote: { fontSize: 13, lineHeight: 18, fontWeight: '400' },
  caption: { fontSize: 12, lineHeight: 16, fontWeight: '600' },
  amount: { fontSize: 40, lineHeight: 46, fontWeight: '700' },
} as const;

/** Minimum touch target in points. */
export const minTouch = 44;

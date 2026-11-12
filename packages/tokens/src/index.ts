// Tenmina design tokens, version 3: "Bloc" (November 2026). Used by the client app
// and Tenmina Field; the portal uses the same values as CSS custom properties (03 6.1b).
// Black or white grounds. Lime for proof and the main action. Orange, used
// sparingly, for anything that needs the client. Yellow appears only as the
// Amber verdict, so a warning never looks like decoration.
// Type: Bricolage Grotesque for words and numbers, IBM Plex Mono for codes,
// references, dates and labels.

export const brand = {
  ink: '#0B0B0B',
  paper: '#FFFFFF',
  lime: '#A3EE5B',
  limeDeep: '#86C94A',
  orange: '#FF6A3D',
  /** Verdict colours. Never used as decoration. */
  amber: '#FDE24F',
  red: '#FF5A4E',
} as const;

/**
 * A ground is the background a screen sits on. Bloc screens are either paper
 * (white) or ink (black). In system dark mode every screen uses ink.
 */
export type Ground = 'paper' | 'ink';

export const paper = {
  ground: '#FFFFFF',
  surface: '#F3F1EC',
  surfaceAlt: '#E9E6DF',
  raised: '#0B0B0B',
  onRaised: '#F7F6F2',
  text: '#0B0B0B',
  textMuted: '#6A675F',
  line: '#ECEAE4',
  lineStrong: '#D6D3CB',
  accent: '#0B0B0B',
  onAccent: '#F7F6F2',
} as const;

export type Palette = { [K in keyof typeof paper]: string };

export const ink: Palette = {
  ground: '#0B0B0B',
  surface: '#1A1A1A',
  surfaceAlt: '#242424',
  raised: '#FFFFFF',
  onRaised: '#0B0B0B',
  text: '#F7F6F2',
  textMuted: '#A9A69E',
  line: '#2C2C2C',
  lineStrong: '#3A3A3A',
  accent: '#A3EE5B',
  onAccent: '#0B0B0B',
};

export const space = { 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 7: 32, 8: 40 } as const;

export const radius = { sm: 8, md: 14, lg: 20, xl: 24, pill: 999 } as const;

/** Font family names as registered with expo-font in the root layout. */
export const font = {
  regular: 'BricolageGrotesque_400Regular',
  semibold: 'BricolageGrotesque_600SemiBold',
  bold: 'BricolageGrotesque_700Bold',
  heavy: 'BricolageGrotesque_800ExtraBold',
  mono: 'IBMPlexMono_500Medium',
  monoBold: 'IBMPlexMono_600SemiBold',
} as const;

/** Type scale. Custom fonts carry their weight in the family, so no fontWeight here. */
export const type = {
  display: { fontFamily: font.heavy, fontSize: 40, lineHeight: 42, letterSpacing: -1.6 },
  largeTitle: { fontFamily: font.heavy, fontSize: 34, lineHeight: 38, letterSpacing: -1.3 },
  title: { fontFamily: font.heavy, fontSize: 24, lineHeight: 28, letterSpacing: -0.7 },
  headline: { fontFamily: font.bold, fontSize: 17, lineHeight: 22 },
  body: { fontFamily: font.regular, fontSize: 16, lineHeight: 23 },
  callout: { fontFamily: font.regular, fontSize: 15, lineHeight: 20 },
  footnote: { fontFamily: font.regular, fontSize: 13, lineHeight: 18 },
  amount: { fontFamily: font.heavy, fontSize: 36, lineHeight: 40, letterSpacing: -1.3 },
  label: { fontFamily: font.monoBold, fontSize: 11, lineHeight: 14, letterSpacing: 0.9 },
  mono: { fontFamily: font.mono, fontSize: 12, lineHeight: 16 },
} as const;

/** Minimum touch target in points. */
export const minTouch = 44;

/** How long the client holds the approve button, in milliseconds. */
export const holdToApproveMs = 1200;

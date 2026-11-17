import { createContext, useContext, useEffect, useState } from 'react';
import { AccessibilityInfo, Platform, useColorScheme } from 'react-native';
import { ink, paper, type Ground, type Palette } from '@tenmina/tokens';

/** The ground of the screen being drawn. Screens set it; components read it. */
export const GroundContext = createContext<Ground>('paper');

/**
 * The palette of the block being drawn on, when it is not the screen's ground: a
 * black strip, a lime or orange panel, the white ticket. Text, labels, buttons and
 * rows inside such a block take their colours from it, so they never draw the
 * screen's text colour on a block of the same colour (white on white in dark mode).
 */
export const PaletteContext = createContext<Palette | null>(null);

/** In system dark mode every screen is ink. Otherwise the screen's own ground wins. */
export function useGround(requested?: Ground): Ground {
  const inherited = useContext(GroundContext);
  const scheme = useColorScheme();
  if (scheme === 'dark') return 'ink';
  return requested ?? inherited;
}

/**
 * The palette to draw with. A screen asks for its ground; a component inside a
 * block of another colour gets that block's palette (PaletteContext).
 */
export function usePalette(requested?: Ground): Palette {
  const block = useContext(PaletteContext);
  const g = useGround(requested);
  if (block && !requested) return block;
  return g === 'ink' ? ink : paper;
}

/** True when the phone asks for less motion. Every animation checks this. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    let live = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((v) => live && setReduced(v));
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduced);
    return () => {
      live = false;
      sub.remove();
    };
  }, []);
  return reduced;
}

/** True when VoiceOver or TalkBack is on. The web preview always reports false: react-native-web cannot tell. */
export function useScreenReader(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (Platform.OS === 'web') return;
    let live = true;
    void AccessibilityInfo.isScreenReaderEnabled().then((v) => live && setOn(v));
    const sub = AccessibilityInfo.addEventListener('screenReaderChanged', setOn);
    return () => {
      live = false;
      sub.remove();
    };
  }, []);
  return on;
}

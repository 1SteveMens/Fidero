import { createContext, useContext, useEffect, useState } from 'react';
import { AccessibilityInfo, Platform, useColorScheme } from 'react-native';
import { ink, paper, type Ground, type Palette } from '@fidero/tokens';

/** The ground of the screen being drawn. Screens set it; components read it. */
export const GroundContext = createContext<Ground>('paper');

/** In system dark mode every screen is ink. Otherwise the screen's own ground wins. */
export function useGround(requested?: Ground): Ground {
  const inherited = useContext(GroundContext);
  const scheme = useColorScheme();
  if (scheme === 'dark') return 'ink';
  return requested ?? inherited;
}

export function usePalette(requested?: Ground): Palette {
  return useGround(requested) === 'ink' ? ink : paper;
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

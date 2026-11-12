import Svg, { Path } from 'react-native-svg';
import { brand } from '@tenmina/tokens';

/** The Tenmina mark: a lime square with notched sides and a check. */
export function Mark({ size = 32 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 30 30" accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Path d="M6 3h18a3 3 0 0 1 3 3v6a3 3 0 0 0 0 6v6a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3v-6a3 3 0 0 0 0-6V6a3 3 0 0 1 3-3z" fill={brand.lime} />
      <Path d="M10 15.5l3.2 3.2L20 11.5" stroke={brand.ink} strokeWidth={3} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </Svg>
  );
}

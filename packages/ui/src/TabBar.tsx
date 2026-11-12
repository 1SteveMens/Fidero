import { Pressable, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import type { BottomTabBarProps } from 'expo-router/tabs';
import { brand, minTouch, space } from '@tenmina/tokens';
import { T, haptic, type IconName } from './ui';


/**
 * The Bloc tab bar: a black bar docked above the home indicator. The current
 * tab is a lime block with its name; the others are icons with spoken labels.
 */
export function TabBar({ state, descriptors, navigateToTab, insets, icons, badges }: BottomTabBarProps & {
  /** Icon per route name. Outline variants are used for tabs that are not selected. */
  icons: Record<string, IconName>;
  /** Optional count per route name, shown as an orange badge (for example, items waiting to upload). */
  badges?: Record<string, number | undefined>;
}) {
  return (
    <View pointerEvents="box-none" style={{ position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: space[4], paddingBottom: Math.max(insets.bottom, space[4]) }}>
      <View accessibilityRole="tablist" style={{ height: 66, borderRadius: 22, backgroundColor: brand.ink, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 10, borderWidth: 1, borderColor: '#262626' }}>
        {state.routes.map((route, i) => {
          const focused = state.index === i;
          const label = descriptors[route.key]?.options.title ?? route.name;
          const icon = icons[route.name] ?? 'ellipse';
          const badge = badges?.[route.name];
          return (
            <Pressable
              key={route.key}
              accessibilityRole="tab"
              accessibilityState={{ selected: focused }}
              accessibilityLabel={badge ? `${label}, ${badge}` : label}
              onPress={() => {
                if (!focused) {
                  haptic('tap');
                  navigateToTab(route.key);
                }
              }}
              style={({ pressed }) => ({
                height: 46,
                minWidth: minTouch + 8,
                paddingHorizontal: focused ? space[4] : 0,
                borderRadius: 14,
                backgroundColor: focused ? brand.lime : 'transparent',
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'center',
                gap: space[2],
                opacity: pressed ? 0.75 : 1,
              })}
            >
              <View>
                <Ionicons name={focused ? icon : (`${icon}-outline` as IconName)} size={21} color={focused ? brand.ink : '#F7F6F2'} />
                {badge && !focused ? (
                  <View style={{ position: 'absolute', top: -7, right: -12, minWidth: 18, height: 18, borderRadius: 9, paddingHorizontal: 4, backgroundColor: brand.orange, alignItems: 'center', justifyContent: 'center' }}>
                    <T v="label" color={brand.ink} style={{ fontSize: 10, lineHeight: 12 }}>{String(badge)}</T>
                  </View>
                ) : null}
              </View>
              {focused ? (
                <T v="headline" color={brand.ink} style={{ fontSize: 15 }}>
                  {label}
                </T>
              ) : null}
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

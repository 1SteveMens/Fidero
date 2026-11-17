import { useState, type ReactNode } from 'react';
import { Linking, Pressable, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Label, ListRow, Panel, Screen, T, usePalette, type IconName } from '@tenmina/ui';

export interface HelpAnswer {
  q: string;
  a: string;
}

interface Contact {
  icon: IconName;
  title: string;
  detail: string;
  url: string;
}

/**
 * Ways to reach Tenmina, from the build's settings: EXPO_PUBLIC_HELP_EMAIL,
 * EXPO_PUBLIC_HELP_PHONE and EXPO_PUBLIC_HELP_WHATSAPP (a number with its
 * country code). The real addresses and opening hours are [TO VERIFY]; a row
 * shows only when its setting is there, so the app never shows a made-up one.
 */
export function helpContacts(): Contact[] {
  const email = process.env.EXPO_PUBLIC_HELP_EMAIL ?? '';
  const phone = process.env.EXPO_PUBLIC_HELP_PHONE ?? '';
  const whatsapp = process.env.EXPO_PUBLIC_HELP_WHATSAPP ?? '';
  const out: Contact[] = [];
  if (email) out.push({ icon: 'mail-outline', title: 'Email Tenmina', detail: email, url: `mailto:${email}` });
  if (whatsapp) out.push({ icon: 'logo-whatsapp', title: 'WhatsApp Tenmina', detail: whatsapp, url: `https://wa.me/${whatsapp.replace(/\D/g, '')}` });
  if (phone) out.push({ icon: 'call-outline', title: 'Call Tenmina', detail: phone, url: `tel:${phone.replace(/\s/g, '')}` });
  return out;
}

/**
 * Help inside the app (both apps): short answers, then the ways to reach a
 * person at Tenmina, and the safety rule that Tenmina never asks for a code.
 * Nothing here sends the person to the website.
 */
export function HelpScreen({ answers, ground = 'ink', extra }: { answers: HelpAnswer[]; ground?: 'ink' | 'paper'; extra?: ReactNode }) {
  const p = usePalette(ground);
  const [open, setOpen] = useState<number | null>(null);
  const contacts = helpContacts();
  return (
    <Screen ground={ground} back title="Help">
      <View style={{ borderRadius: 16, borderWidth: 2, borderColor: brand.lime, padding: space[4], gap: space[2] }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
          <Ionicons name="shield-checkmark" size={20} color={brand.lime} />
          <T v="headline" style={{ flex: 1 }}>Tenmina will never call you for a code</T>
        </View>
        <T v="callout">Never share a code from a text message, your password or your authenticator code with anyone, even someone who says they work for Tenmina. We never change who gets paid because of a message, email or call.</T>
      </View>

      <Label>Common questions</Label>
      <Panel style={{ paddingVertical: space[1], gap: 0 }}>
        {answers.map((x, i) => (
          <Pressable
            key={x.q}
            onPress={() => setOpen(open === i ? null : i)}
            accessibilityRole="button"
            accessibilityState={{ expanded: open === i }}
            style={{ minHeight: 52, paddingVertical: space[3], gap: space[2], borderBottomWidth: i < answers.length - 1 ? 1 : 0, borderBottomColor: p.line }}
          >
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              <T v="headline" style={{ flex: 1, fontSize: 15 }}>{x.q}</T>
              <Ionicons name={open === i ? 'chevron-up' : 'chevron-down'} size={18} color={p.textMuted} />
            </View>
            {open === i ? <T v="callout" muted>{x.a}</T> : null}
          </Pressable>
        ))}
      </Panel>

      {extra}

      <Label>Talk to a person</Label>
      {contacts.length ? (
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          {contacts.map((c, i) => (
            <ListRow key={c.url} icon={c.icon} title={c.title} detail={c.detail} onPress={() => void Linking.openURL(c.url)} last={i === contacts.length - 1} />
          ))}
        </Panel>
      ) : (
        <T v="callout" muted>Phone, WhatsApp and email help are not set up in this version of the app yet.</T>
      )}
    </Screen>
  );
}

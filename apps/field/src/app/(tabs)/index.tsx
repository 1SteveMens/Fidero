import { Pressable, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, font, radius, space } from '@tenmina/tokens';
import { ArrowBox, Chip, ErrorView, Label, Loading, Mark, Panel, Rise, Screen, T, haptic } from '@tenmina/ui';
import { useField, useFieldLoad } from '../../store';
import type { FieldJob } from '@tenmina/shared';

function today(): string {
  return new Date().toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).toUpperCase();
}

export function OnlineChip() {
  const { online } = useField();
  return online ? <Chip tone="lime" label="Online" /> : <Chip tone="orange" icon="cloud-offline" label="Offline" />;
}

function JobCard({ job, next, sent }: { job: FieldJob; next: boolean; sent: boolean }) {
  const bg = next ? brand.orange : undefined;
  return (
    <Panel
      tone={next ? 'orange' : 'surface'}
      onPress={() => router.push(`/job/${job.id}`)}
      accessibilityLabel={`${job.startsAt}. ${job.title}. ${job.site.name}. ${sent ? 'Sent' : next ? 'Next' : ''}`}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], backgroundColor: bg }}
    >
      <View style={{ width: 58, gap: 2 }}>
        <Label color={next ? brand.ink : undefined}>{job.startsAt}</Label>
        {next ? <T v="footnote" color={brand.ink}>Next</T> : sent ? <Chip tone="lime" label="Sent" /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <T v="headline" color={next ? brand.ink : undefined} style={{ fontSize: 17 }}>{job.title}</T>
        <T v="footnote" color={next ? '#3A1408' : undefined} muted={!next}>{`${job.site.name} · ${job.detail}`}</T>
      </View>
      <ArrowBox arrow={next ? brand.orange : brand.lime} />
    </Panel>
  );
}

export default function Jobs() {
  const { queue, submitted, role } = useField();
  const { data, error, reload } = useFieldLoad(async (api) => ({ me: await api.me(), jobs: await api.listJobs() }), 'jobs');
  const waiting = queue.filter((q) => q.state !== 'sent').length;
  const nextId = data?.jobs.find((j) => !submitted[j.id])?.id;

  return (
    <Screen ground="paper" tabs>
      <Rise style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
        <Mark size={30} />
        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'baseline', gap: space[2] }}>
          <T v="title" style={{ fontFamily: font.heavy, letterSpacing: -1 }}>tenmina</T>
          <Label>Field</Label>
        </View>
        <OnlineChip />
      </Rise>
      <Rise delay={60}>
        <T v="largeTitle" header>Today</T>
        <Label>{data ? `${today()} · ${data.me.name} · ${data.me.roleLabel}` : today()}</Label>
      </Rise>
      {waiting > 0 ? (
        <Rise delay={100}>
          <Pressable
            onPress={() => {
              haptic('tap');
              router.push('/queue');
            }}
            accessibilityRole="button"
            style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space[3], backgroundColor: brand.ink, borderRadius: radius.md + 2, padding: space[3], opacity: pressed ? 0.85 : 1 })}
          >
            <Ionicons name="cloud-upload-outline" size={20} color={brand.lime} />
            <T v="callout" color="#F7F6F2" style={{ flex: 1 }}>{`${waiting} ${waiting === 1 ? 'item' : 'items'} saved on this phone. They upload when you have signal.`}</T>
            <Ionicons name="chevron-forward" size={18} color="#A9A69E" />
          </Pressable>
        </Rise>
      ) : null}
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data?.jobs.map((j, i) => (
        <Rise key={j.id} delay={140 + i * 80}>
          <JobCard job={j} next={j.id === nextId} sent={!!submitted[j.id]} />
        </Rise>
      ))}
      {data && role !== 'carer' ? (
        <Rise delay={400} style={{ flexDirection: 'row', gap: space[2], alignItems: 'flex-start' }}>
          <Ionicons name="shield-checkmark-outline" size={18} color={brand.ink} />
          <T v="footnote" muted style={{ flex: 1 }}>You have no link to the people on these jobs. If that changes, tell us before you start (RUL-10).</T>
        </Rise>
      ) : null}
    </Screen>
  );
}

import { useEffect } from 'react';
import { useLocalSearchParams } from 'expo-router';
import { Screen } from '@tenmina/ui';
import { Empty } from '@tenmina/mobile';
import { jobKey, useField, useJob } from '../../../store';
import { InspectionScreen } from '../../../screens/Inspection';
import { EvidenceJobScreen } from '../../../screens/EvidenceJob';
import { VisitScreen } from '../../../screens/Visit';
import type { Job } from '../../../types';

/**
 * One job, opened from My jobs: the screen depends on what the work is. A
 * copy of the job is kept with its progress, so a finished visit still shows
 * its last step after the server takes it off the list.
 */
export default function JobScreen() {
  const { type, id } = useLocalSearchParams<{ type: string; id: string }>();
  const { progress, setProgress } = useField();
  const live = useJob(type, id);
  const key = jobKey(type, id);
  const job = live ?? (progress(key).job as Job | undefined);
  useEffect(() => {
    if (live) setProgress(key, { job: live });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live?.updated_at, key]);
  if (!job) {
    return (
      <Screen back>
        <Empty icon="cloud-offline-outline" title="This job is not on the phone" detail="It may have been reassigned or finished. Sync again from My jobs." />
      </Screen>
    );
  }
  if (job.kind === 'inspection' || job.subject_type === 'milestone_inspection' || job.subject_type === 'property_inspection') return <InspectionScreen job={job} />;
  if (job.kind === 'care_visit' || job.subject_type === 'care_visit') return <VisitScreen job={job} />;
  return <EvidenceJobScreen job={job} />;
}

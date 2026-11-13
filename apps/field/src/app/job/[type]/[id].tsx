import { useLocalSearchParams } from 'expo-router';
import { Screen } from '@tenmina/ui';
import { Empty } from '@tenmina/mobile';
import { useJob } from '../../../store';
import { InspectionScreen } from '../../../screens/Inspection';
import { EvidenceJobScreen } from '../../../screens/EvidenceJob';
import { VisitScreen } from '../../../screens/Visit';

/** One job, opened from My jobs: the screen depends on what the work is. */
export default function JobScreen() {
  const { type, id } = useLocalSearchParams<{ type: string; id: string }>();
  const job = useJob(type, id);
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

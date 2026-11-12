import { useLocalSearchParams } from 'expo-router';
import { ErrorView, Loading, Screen } from '@tenmina/ui';
import { useFieldLoad } from '../../store';
import { InspectionScreen } from '../../screens/Inspection';
import { MilestoneScreen } from '../../screens/Milestone';
import { VisitScreen } from '../../screens/Visit';

export default function JobScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: job, error, reload } = useFieldLoad((api) => api.getJob(id), `job-${id}`);
  if (error) return <Screen back><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!job) return <Screen back><Loading /></Screen>;
  if (job.kind === 'inspection') return <InspectionScreen job={job} />;
  if (job.kind === 'milestone') return <MilestoneScreen job={job} />;
  return <VisitScreen job={job} />;
}

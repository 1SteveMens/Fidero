export const ORDER_STEPS = ['What to check', 'The plot', 'Documents and seller', 'Check and agree', 'Pay'];

export function orderSteps(now: number) {
  return ORDER_STEPS.map((label, i) => ({ label, state: (i < now ? 'done' : i === now ? 'now' : 'next') as 'done' | 'now' | 'next' }));
}

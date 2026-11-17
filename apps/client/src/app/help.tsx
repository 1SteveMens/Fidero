import { HelpScreen, type HelpAnswer } from '@tenmina/mobile';

const ANSWERS: HelpAnswer[] = [
  { q: 'Where is my money?', a: 'At the partner bank, in an account held for you. Tenmina never holds it. The bank pays only a verified institution, supplier or professional, after you approve and two Tenmina staff approve.' },
  { q: 'How do I approve a payment?', a: 'Open the payment, check the amount and who is paid, then press and hold. In this app, Face ID or a fingerprint confirms it. Without them, we text you a code. If you do nothing, nothing is paid.' },
  { q: 'I did not get the code by text message', a: 'Wait a minute, then tap "Send a new code". You can ask for 3 codes in 10 minutes. Check that your number in Account is right. Each code works for 5 minutes, once.' },
  { q: 'Why are approvals by text message paused?', a: 'For 72 hours after your number changes, or after your mobile network tells us the SIM card changed. This stops someone who took over your number from moving money. Face ID in the app or an authenticator app still work if you have them.' },
  { q: 'I lost my phone', a: 'Sign in on another phone and remove the lost one in Account, under "Phones that can approve". If your number moved to a new SIM, change it in Account. Nothing is paid without your approval.' },
  { q: 'I forgot my password', a: 'On the sign-in screen, tap "Forgot your password?". We send one code to your email and one to your phone. You need both.' },
];

/** Help inside the app (SCR-APP-03): answers, then how to reach a person. Never a link to the website. */
export default function Help() {
  return <HelpScreen answers={ANSWERS} />;
}

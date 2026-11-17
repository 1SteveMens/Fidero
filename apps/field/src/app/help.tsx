import { HelpScreen, type HelpAnswer } from '@tenmina/mobile';

const ANSWERS: HelpAnswer[] = [
  { q: 'My photos have not uploaded', a: 'They stay sealed on this phone until there is a signal, then upload by themselves. Account shows how many are waiting. Do not sign out while items are waiting.' },
  { q: 'Why can I not pick a photo from the gallery?', a: 'Evidence is taken in this app only, so Tenmina can prove when and where it was taken. Photos from the gallery are not accepted.' },
  { q: 'I changed phones', a: 'Sign in on the new phone and register it. Send everything waiting on the old phone first, or ask Tenmina to remove the old phone.' },
  { q: 'I forgot my password', a: 'On the sign-in screen, tap "Forgot your password?". We email you a code.' },
];

/** Help inside Tenmina Field (SCR-MOB-13): answers, then how to reach a person. Never a link to the website. */
export default function Help() {
  return <HelpScreen answers={ANSWERS} />;
}

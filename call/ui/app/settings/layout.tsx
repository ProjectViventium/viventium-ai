import localFont from 'next/font/local';
import './install.css';
import './settings.css';

// The typeface of xperfect.ai, self-hosted: Inter Tight (SIL OFL, fonts/InterTight-OFL.txt).
const tight = localFont({
  display: 'swap',
  variable: '--font-ui',
  src: '../../fonts/InterTight-Variable.woff2',
  weight: '100 900',
});

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <div className={`${tight.variable} vs`}>{children}</div>;
}

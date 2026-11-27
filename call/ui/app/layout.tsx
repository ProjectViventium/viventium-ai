import localFont from 'next/font/local';
import { CallChrome } from '@/components/app/call-chrome';
import { ThemeProvider } from '@/components/app/theme-provider';
import { ThemeToggle } from '@/components/app/theme-toggle';
import { cn } from '@/lib/shadcn/utils';
import '@/styles/globals.css';

// Self-hosted (SIL OFL, fonts/PublicSans-OFL.txt): the page loads nothing from the internet.
const publicSans = localFont({
  display: 'swap',
  variable: '--font-public-sans',
  src: '../fonts/PublicSans-Variable.ttf',
  weight: '100 900',
});

const commitMono = localFont({
  display: 'swap',
  variable: '--font-commit-mono',
  src: [
    {
      path: '../fonts/CommitMono-400-Regular.otf',
      weight: '400',
      style: 'normal',
    },
    {
      path: '../fonts/CommitMono-700-Regular.otf',
      weight: '700',
      style: 'normal',
    },
    {
      path: '../fonts/CommitMono-400-Italic.otf',
      weight: '400',
      style: 'italic',
    },
    {
      path: '../fonts/CommitMono-700-Italic.otf',
      weight: '700',
      style: 'italic',
    },
  ],
});

interface RootLayoutProps {
  children: React.ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn(
        publicSans.variable,
        commitMono.variable,
        'scroll-smooth font-sans antialiased'
      )}
    >
      <head>
        <title>Viventium AI</title>
        <meta name="description" content="Viventium AI by xPerfect.ai: your own AI, on your Mac" />
      </head>
      <body className="overflow-x-hidden">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <CallChrome>
            <header className="fixed top-0 left-0 z-50 hidden w-full flex-row justify-between p-6 md:flex">
              <a
                target="_blank"
                rel="noopener noreferrer"
                href="https://viventium.ai"
                aria-label="Viventium"
                className="text-foreground block size-7 scale-100 transition-transform duration-300 hover:scale-110"
                style={{
                  background: 'currentColor',
                  WebkitMask: "url('/marks/viventium-v.svg') center / contain no-repeat",
                  mask: "url('/marks/viventium-v.svg') center / contain no-repeat",
                }}
              />
              <a
                target="_blank"
                rel="noopener noreferrer"
                href="https://viventium.ai"
                className="text-foreground font-mono text-xs font-bold tracking-wider uppercase underline-offset-4 hover:underline"
              >
                Viventium.ai
              </a>
            </header>
          </CallChrome>

          {children}
          <div className="group fixed bottom-0 left-1/2 z-50 mb-2 -translate-x-1/2">
            <ThemeToggle className="translate-y-20 transition-transform delay-150 duration-300 group-hover:translate-y-0" />
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}

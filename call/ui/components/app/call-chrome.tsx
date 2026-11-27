'use client';

import { usePathname } from 'next/navigation';

// The call screen's own header (her mark, viventium.ai) stays off her settings page, which has its own look.
export function CallChrome({ children }: { children: React.ReactNode }) {
  return usePathname().startsWith('/settings') ? null : <>{children}</>;
}

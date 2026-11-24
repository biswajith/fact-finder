import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react';

/**
 * The app is light only. The dark tokens in styles.css stay, unused, in case a dark theme comes back;
 * everything that asks for the theme gets "light".
 */
interface ThemeCtx {
  /** What is shown: always light. */
  resolved: 'light';
}
const Ctx = createContext<ThemeCtx | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.dataset.theme = 'light';
  }, []);
  const value = useMemo<ThemeCtx>(() => ({ resolved: 'light' }), []);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('useTheme outside ThemeProvider');
  return c;
}

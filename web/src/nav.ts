// Page names and their URL hashes (#/overview ...). Shared by the store, the shell and the pages.
export type PageName = 'overview' | 'facts' | 'conflicts' | 'changes' | 'report' | 'compare' | 'chatlog' | 'new';

export const PAGE_NAMES: PageName[] = ['overview', 'facts', 'conflicts', 'changes', 'report', 'compare', 'chatlog', 'new'];

export const PAGE_TITLES: Record<PageName, string> = {
  overview: 'Overview',
  facts: 'Facts',
  conflicts: 'Conflicts',
  changes: 'Changes',
  report: 'Run report',
  compare: 'Compare',
  chatlog: 'Chat log',
  new: 'New run',
};

export function pageFromHash(hash: string): PageName {
  const name = hash.replace(/^#\/?/, '').split(/[/?]/)[0];
  return (PAGE_NAMES as string[]).includes(name) ? (name as PageName) : 'overview';
}

export const hashForPage = (p: PageName): string => `#/${p}`;

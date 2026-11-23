// Page names and their URL hashes (#/overview ...). Shared by the store, the shell and the pages.
export type PageName = 'documents' | 'overview' | 'facts' | 'conflicts' | 'changes' | 'report' | 'compare' | 'chatlog';

export const PAGE_NAMES: PageName[] = ['documents', 'overview', 'facts', 'conflicts', 'changes', 'report', 'compare', 'chatlog'];

export function pageFromHash(hash: string): PageName {
  const name = hash.replace(/^#\/?/, '').split(/[/?]/)[0];
  if (name === 'new') return 'documents'; // the old name of the page keeps working
  return (PAGE_NAMES as string[]).includes(name) ? (name as PageName) : 'overview';
}

export const hashForPage = (p: PageName): string => `#/${p}`;

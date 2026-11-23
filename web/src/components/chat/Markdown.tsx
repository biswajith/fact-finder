import { Fragment } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { linkifyFactTokens } from '../../factTokens';
import { splitBlocks } from '../../chatBlocks';
import { CiteChip } from '../CitationChip';
import { SourceSnippet } from './SourceSnippet';
import { Timeline } from './Timeline';

const keepFactUrls = (url: string) => (url.startsWith('fact:') ? url : defaultUrlTransform(url));

/** Assistant text as safe Markdown (no raw HTML), with fact ids shown as citation chips. */
function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={keepFactUrls}
        components={{
          a({ href, children, node: _node, ...rest }) {
            if (href?.startsWith('fact:')) {
              const ids = href.slice(5).split(',').filter(Boolean);
              return (
                <span className="cite-group">
                  {ids.map((id) => (
                    <Fragment key={id}><CiteChip id={id} /></Fragment>
                  ))}
                </span>
              );
            }
            return <a {...rest} href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
          },
          table({ children }) {
            return <div className="md-table"><table>{children}</table></div>;
          },
        }}
      >
        {linkifyFactTokens(text)}
      </ReactMarkdown>
    </div>
  );
}

/** An answer: Markdown parts, with the source and timeline blocks drawn from stored facts. `streaming` holds back an unfinished block line. */
export function ChatMarkdown({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const parts = splitBlocks(text, { streaming });
  if (parts.length === 1 && parts[0].kind === 'text') return <Markdown text={parts[0].text} />;
  return (
    <>
      {parts.map((p, i) =>
        p.kind === 'text' ? <Markdown key={i} text={p.text} />
          : p.kind === 'source' ? <SourceSnippet key={i} factId={p.factId} />
            : <Timeline key={i} factIds={p.factIds} />)}
    </>
  );
}

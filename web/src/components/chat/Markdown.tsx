import { Fragment } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { linkifyFactTokens } from '../../factTokens';
import { CiteChip } from '../CitationChip';

const keepFactUrls = (url: string) => (url.startsWith('fact:') ? url : defaultUrlTransform(url));

/** Assistant text as safe Markdown (no raw HTML), with fact ids shown as citation chips. */
export function ChatMarkdown({ text }: { text: string }) {
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

import { Fragment, type ReactNode } from "react";
import { parseBlocks, type Block, type Inline } from "../lib/markdown";

// Renders the safe tree from lib/markdown.ts as React elements. No dangerouslySetInnerHTML anywhere: text is always
// a React text node, so markup written by the model or found in a document can never execute.

function inline(nodes: Inline[]): ReactNode[] {
  return nodes.map((n, i) => {
    switch (n.t) {
      case "text":
        return <Fragment key={i}>{n.v}</Fragment>;
      case "br":
        return <br key={i} />;
      case "bold":
        return <strong key={i}>{inline(n.c)}</strong>;
      case "italic":
        return <em key={i}>{inline(n.c)}</em>;
      case "code":
        return <code key={i}>{n.v}</code>;
      case "link":
        return (
          <a key={i} href={n.href} target="_blank" rel="noopener noreferrer">
            {inline(n.c)}
          </a>
        );
      case "cite":
        return (
          <sup key={i} className="cite" title={`Source ${n.n}`}>
            {n.n}
          </sup>
        );
    }
  });
}

function block(b: Block, i: number): ReactNode {
  switch (b.t) {
    case "p":
      return <p key={i}>{inline(b.c)}</p>;
    case "h":
      return b.level === 1 ? <h3 key={i}>{inline(b.c)}</h3> : b.level === 2 ? <h4 key={i}>{inline(b.c)}</h4> : <h5 key={i}>{inline(b.c)}</h5>;
    case "ul":
      return <ul key={i}>{b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ul>;
    case "ol":
      return <ol key={i} start={b.start}>{b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ol>;
    case "code":
      return <pre key={i}><code>{b.v}</code></pre>;
    case "hr":
      return <hr key={i} />;
    case "table":
      return (
        <div key={i} className="md-table">
          <table>
            <thead><tr>{b.head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
            <tbody>
              {b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c)}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
      );
  }
}

export function Markdown({ text, streaming = false }: { text: string; streaming?: boolean }) {
  return <div className={`md${streaming ? " streaming" : ""}`}>{parseBlocks(text).map(block)}</div>;
}

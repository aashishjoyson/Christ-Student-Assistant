// A small, SAFE markdown parser for chat answers: it produces a typed tree, never HTML, so nothing the model (or a
// retrieved document) writes can inject markup. Supports paragraphs, line breaks, headings, bullet/numbered lists, tables,
// code, **bold**, *italic*, `code`, [links](https://...), bare URLs and [1] citation markers. Unclosed markers stay literal,
// so half-streamed text renders sensibly. Only erasable TypeScript syntax is used (Node can run this file directly in tests).

export type Inline =
  | { t: "text"; v: string }
  | { t: "br" }
  | { t: "bold"; c: Inline[] }
  | { t: "italic"; c: Inline[] }
  | { t: "code"; v: string }
  | { t: "link"; href: string; c: Inline[] }
  | { t: "cite"; n: string };

export type Block =
  | { t: "p"; c: Inline[] }
  | { t: "h"; level: 1 | 2 | 3; c: Inline[] }
  | { t: "ul"; items: Inline[][] }
  | { t: "ol"; start: number; items: Inline[][] }
  | { t: "table"; head: Inline[][]; rows: Inline[][][] }
  | { t: "code"; v: string }
  | { t: "hr" };

const URL_RE = /\b(?:https?:\/\/|www\.)[^\s<>()]*[^\s<>().,;:!?'"\]]/gi;
const WORDCHAR = /[A-Za-z0-9]/;

/** Only http(s), mailto and bare www. links are ever turned into anchors. */
export function safeHref(raw: string): string | null {
  const url = raw.trim();
  const candidate = /^www\./i.test(url) ? `https://${url}` : url;
  if (!/^(https?:|mailto:)/i.test(candidate)) return null;
  try {
    new URL(candidate);
    return candidate;
  } catch {
    return null;
  }
}

function pushText(out: Inline[], text: string): void {
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const href = safeHref(m[0]);
    if (!href) continue;
    if (m.index > last) out.push({ t: "text", v: text.slice(last, m.index) });
    out.push({ t: "link", href, c: [{ t: "text", v: m[0] }] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ t: "text", v: text.slice(last) });
}

function italicEnd(src: string, i: number, mark: string): number {
  const next = src[i + 1];
  if (next === undefined || /\s/.test(next) || next === mark) return -1;
  const prev = src[i - 1];
  if (mark === "_" && prev !== undefined && WORDCHAR.test(prev)) return -1; // snake_case stays literal
  for (let j = i + 1; j < src.length; j++) {
    if (src[j] === "\n") return -1;
    if (src[j] === mark && !/\s/.test(src[j - 1]) && (mark === "*" || !WORDCHAR.test(src[j + 1] ?? ""))) return j;
  }
  return -1;
}

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let buf = "";
  const flush = () => {
    if (buf) {
      pushText(out, buf);
      buf = "";
    }
  };
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === "`") {
      const end = src.indexOf("`", i + 1);
      if (end > i + 1) {
        flush();
        out.push({ t: "code", v: src.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    } else if (ch === "*" && src[i + 1] === "*") {
      const end = src.indexOf("**", i + 2);
      if (end > i + 2 && !/\s/.test(src[i + 2]) && !/\s/.test(src[end - 1])) {
        flush();
        out.push({ t: "bold", c: parseInline(src.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    } else if (ch === "*" || ch === "_") {
      const end = italicEnd(src, i, ch);
      if (end > i + 1) {
        flush();
        out.push({ t: "italic", c: parseInline(src.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    } else if (ch === "[") {
      const rest = src.slice(i);
      const link = /^\[([^\]\n]+)\]\(([^)\s]+)\)/.exec(rest);
      if (link) {
        const href = safeHref(link[2]);
        flush();
        out.push(href ? { t: "link", href, c: [{ t: "text", v: link[1] }] } : { t: "text", v: link[1] });
        i += link[0].length;
        continue;
      }
      const cite = /^\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]/.exec(rest);
      if (cite) {
        flush();
        out.push({ t: "cite", n: cite[1].replace(/\s+/g, "") });
        i += cite[0].length;
        continue;
      }
    } else if (ch === "\n") {
      flush();
      out.push({ t: "br" });
      i += 1;
      continue;
    }
    buf += ch;
    i += 1;
  }
  flush();
  return out;
}

const BULLET = /^(\s*)[-*•]\s+(.*)$/;
const NUMBERED = /^(\s*)(\d{1,3})[.)]\s+(.*)$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  const flushPara = () => {
    if (para.length) {
      blocks.push({ t: "p", c: parseInline(para.join("\n")) });
      para = [];
    }
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flushPara();
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
      i += 1;
      blocks.push({ t: "code", v: code.join("\n") });
      continue;
    }
    if (!line.trim()) {
      flushPara();
      i += 1;
      continue;
    }
    const heading = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
    if (heading) {
      flushPara();
      blocks.push({ t: "h", level: Math.min(3, heading[1].length) as 1 | 2 | 3, c: parseInline(heading[2]) });
      i += 1;
      continue;
    }
    if (RULE.test(line)) {
      flushPara();
      blocks.push({ t: "hr" });
      i += 1;
      continue;
    }
    if (line.trim().startsWith("|") && i + 1 < lines.length && TABLE_SEPARATOR.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      flushPara();
      const head = splitRow(line).map(parseInline);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]).map(parseInline));
      blocks.push({ t: "table", head, rows });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      flushPara();
      const ordered = !!numbered;
      const start = numbered ? Number(numbered[2]) : 1;
      const items: string[] = [];
      while (i < lines.length) {
        const b = BULLET.exec(lines[i]);
        const n = NUMBERED.exec(lines[i]);
        const match = ordered ? n : b;
        if (match) {
          items.push(ordered ? (match as RegExpExecArray)[3] : (match as RegExpExecArray)[2]);
          i += 1;
        } else if (items.length && lines[i].trim() && /^\s{2,}/.test(lines[i]) && !b && !n) {
          items[items.length - 1] += ` ${lines[i].trim()}`; // an indented continuation line belongs to the item
          i += 1;
        } else {
          break;
        }
      }
      const parsed = items.map(parseInline);
      blocks.push(ordered ? { t: "ol", start, items: parsed } : { t: "ul", items: parsed });
      continue;
    }
    para.push(line);
    i += 1;
  }
  flushPara();
  return blocks;
}

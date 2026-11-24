// Run with: npm test   (Node's built-in runner; no extra dependencies)
import assert from "node:assert/strict";
import test from "node:test";

import { parseBlocks, parseInline, safeHref } from "../src/lib/markdown.ts";
import { parseFrame, splitFrames } from "../src/lib/sse.ts";

const text = (v) => ({ t: "text", v });

test("bold, italic, code and citations", () => {
  assert.deepEqual(parseInline("You need **85%** attendance [1][3]."), [
    text("You need "),
    { t: "bold", c: [text("85%")] },
    text(" attendance "),
    { t: "cite", n: "1" },
    { t: "cite", n: "3" },
    text("."),
  ]);
  assert.deepEqual(parseInline("see *this* and `x = 1`"), [text("see "), { t: "italic", c: [text("this")] }, text(" and "), { t: "code", v: "x = 1" }]);
  assert.deepEqual(parseInline("sources [1, 2]"), [text("sources "), { t: "cite", n: "1,2" }]);
});

test("unclosed or stray markers stay literal (half-streamed text)", () => {
  assert.deepEqual(parseInline("**Fees are"), [text("**Fees are")]);
  assert.deepEqual(parseInline("2 * 3 * 4"), [text("2 * 3 * 4")]);
  assert.deepEqual(parseInline("snake_case_name"), [text("snake_case_name")]);
  assert.deepEqual(parseInline("a `code"), [text("a `code")]);
});

test("links: only safe protocols become anchors", () => {
  assert.deepEqual(parseInline("[site](https://example.com/a)"), [{ t: "link", href: "https://example.com/a", c: [text("site")] }]);
  const evil = parseInline("[click](javascript:alert(1))");
  assert.ok(!JSON.stringify(evil).includes('"link"'), "javascript: must never become a link");
  assert.equal(safeHref("javascript:alert(1)"), null);
  assert.equal(safeHref("data:text/html;base64,AAAA"), null);
  assert.equal(safeHref("www.christuniversity.in"), "https://www.christuniversity.in");
  assert.equal(safeHref("mailto:a@b.org"), "mailto:a@b.org");
});

test("bare URLs are linked without swallowing trailing punctuation", () => {
  const out = parseInline("Visit https://www.christuniversity.in/admissions, or www.example.org.");
  const links = out.filter((n) => n.t === "link");
  assert.equal(links[0].href, "https://www.christuniversity.in/admissions");
  assert.equal(links[1].href, "https://www.example.org");
});

test("raw HTML is never interpreted: it stays text", () => {
  const out = parseInline("<script>alert(1)</script> <img src=x onerror=alert(1)>");
  assert.ok(out.every((n) => n.t === "text"));
});

test("paragraphs, soft line breaks, headings and rules", () => {
  const blocks = parseBlocks("## Fees\n\nLine one\nLine two\n\n---\n\nDone");
  assert.equal(blocks[0].t, "h");
  assert.equal(blocks[0].level, 2);
  assert.deepEqual(blocks[1], { t: "p", c: [text("Line one"), { t: "br" }, text("Line two")] });
  assert.equal(blocks[2].t, "hr");
  assert.equal(blocks[3].t, "p");
});

test("bullet and numbered lists, including a list right after a paragraph", () => {
  const blocks = parseBlocks("Fees vary:\n- **Delhi:** 5,80,000 [1]\n- **Bangalore:** 5,70,000\n\n1. First\n2. Second");
  assert.equal(blocks[0].t, "p");
  assert.equal(blocks[1].t, "ul");
  assert.equal(blocks[1].items.length, 2);
  assert.equal(blocks[1].items[0][0].t, "bold");
  assert.deepEqual(blocks[2], { t: "ol", start: 1, items: [[text("First")], [text("Second")]] });
});

test("an indented continuation line joins its list item", () => {
  const blocks = parseBlocks("- first part\n  second part\n- next");
  assert.deepEqual(blocks[0].items[0], [text("first part second part")]);
});

test("tables", () => {
  const blocks = parseBlocks("| Campus | Fee |\n|---|---|\n| Central | 5,80,000 |\n| North | 5,70,000 |");
  assert.equal(blocks[0].t, "table");
  assert.equal(blocks[0].head.length, 2);
  assert.equal(blocks[0].rows.length, 2);
  assert.deepEqual(blocks[0].rows[1][0], [text("North")]);
});

test("code fences, including an unfinished one while streaming", () => {
  assert.deepEqual(parseBlocks("```\nx = 1\n```"), [{ t: "code", v: "x = 1" }]);
  assert.deepEqual(parseBlocks("```\nx = 1"), [{ t: "code", v: "x = 1" }]);
});

test("a realistic answer from the live assistant", () => {
  const answer =
    "**Eligibility:** A score of **450 or above**. [1][2]\n\n**Fees vary by campus:**\n- **Delhi NCR:** ₹5,80,000 per year [1]\n- **Bangalore Kengeri:** ₹5,70,000 per year";
  const blocks = parseBlocks(answer);
  assert.deepEqual(blocks.map((b) => b.t), ["p", "p", "ul"]);
  assert.equal(blocks[2].items.length, 2);
});

test("SSE framing: chunks that split a frame in the middle", () => {
  let { frames, rest } = splitFrames('event: start\ndata: {"a":1}\n\nevent: delta\ndata: {"text":"Hel');
  assert.equal(frames.length, 1);
  assert.deepEqual(parseFrame(frames[0]), { event: "start", data: { a: 1 } });
  ({ frames, rest } = splitFrames(`${rest}lo"}\n\n`));
  assert.deepEqual(parseFrame(frames[0]), { event: "delta", data: { text: "Hello" } });
  assert.equal(rest, "");
});

test("SSE framing: CRLF, comments and junk are tolerated", () => {
  const { frames } = splitFrames('event: delta\r\ndata: {"text":"x"}\r\n\r\n: keep-alive\n\ndata: not json\n\n');
  assert.deepEqual(parseFrame(frames[0]), { event: "delta", data: { text: "x" } });
  assert.equal(parseFrame(frames[1]), null);
  assert.equal(parseFrame(frames[2]), null);
});

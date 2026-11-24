// Server-Sent Events framing for fetch() streams (EventSource cannot POST). Pure functions, testable without a browser.

export interface SseFrame {
  event: string;
  data: unknown;
}

/** Split a buffer into complete frames (blank-line separated) and the unfinished remainder. */
export function splitFrames(buffer: string): { frames: string[]; rest: string } {
  const parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = parts.pop() ?? "";
  return { frames: parts.filter((p) => p.trim().length > 0), rest };
}

/** Parse one frame ("event: x" + "data: {json}" lines). Comments and unparseable frames return null. */
export function parseFrame(frame: string): SseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

type Props = { value: unknown; max?: number };

/** Pretty-prints tool arguments and results, capped so one big payload
 *  cannot push the rest of the trace off screen. */
export default function JsonBlock({ value, max = 4000 }: Props) {
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  const clipped = text.length > max;
  return (
    <pre className="thin-scroll max-h-64 overflow-auto rounded border border-ink-200 bg-ink-50 p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words text-ink-800 dark:border-ink-800 dark:bg-ink-950 dark:text-ink-200">
      {clipped ? text.slice(0, max) : text}
      {clipped && (
        <span className="text-ink-400">
          {"\n… "}
          {text.length - max} more characters
        </span>
      )}
    </pre>
  );
}

import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import type { ChatMessage } from "../types";

type Props = {
  messages: ChatMessage[];
  input: string;
  busy: boolean;
  activity: string | null;
  onInput: (value: string) => void;
  onSend: () => void;
};

export default function ChatPane({
  messages,
  input,
  busy,
  activity,
  onInput,
  onSend,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, activity]);

  return (
    <div className="flex h-full flex-col">
      <div className="thin-scroll flex-1 overflow-y-auto px-5 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-5">
          {messages.map((m, i) => {
            if (m.role === "system") {
              return m.tone === "warn" ? (
                <div
                  key={i}
                  role="alert"
                  className="w-full rounded border-l-4 border-red-500 bg-red-50 px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-line text-red-900 dark:bg-red-950/50 dark:text-red-200"
                >
                  {m.text}
                </div>
              ) : (
                <p
                  key={i}
                  className="self-center rounded border border-ink-200 px-3 py-1.5 text-center font-mono text-[11px] text-ink-400 dark:border-ink-800"
                >
                  {m.text}
                </p>
              );
            }
            const mine = m.role === "user";
            return (
              <div key={i} className={mine ? "self-end" : "self-start"}>
                <div className="mb-1 font-mono text-[10px] uppercase tracking-widest text-ink-400">
                  {mine ? "You" : "Consultant"}
                </div>
                <div
                  className={
                    mine
                      ? "max-w-lg rounded-lg rounded-tr-sm bg-petrol-700 px-3.5 py-2.5 text-sm leading-relaxed text-white"
                      : "prose-sm max-w-none text-[15px] leading-relaxed text-ink-800 dark:text-ink-100"
                  }
                >
                  {mine ? (
                    m.text
                  ) : (
                    <div className="[&_h1]:mt-0 [&_h1]:mb-2 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mt-5 [&_h2]:mb-1.5 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold [&_p]:mb-2.5 [&_ul]:mb-2.5 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:mb-1 [&_table]:my-3 [&_table]:w-full [&_table]:text-xs [&_td]:border-t [&_td]:border-ink-200 [&_td]:py-1 [&_td]:pr-3 [&_th]:py-1 [&_th]:pr-3 [&_th]:text-left [&_th]:font-mono [&_th]:text-[10px] [&_th]:uppercase [&_th]:tracking-wider [&_th]:text-ink-400 [&_blockquote]:border-l-2 [&_blockquote]:border-ink-200 [&_blockquote]:pl-3 [&_blockquote]:text-ink-600 dark:[&_td]:border-ink-800 dark:[&_blockquote]:border-ink-800 dark:[&_blockquote]:text-ink-400">
                      <Markdown>{m.text}</Markdown>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {activity && (
            <p
              aria-live="polite"
              className="self-start font-mono text-[11px] text-ink-400"
            >
              <span className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-amber-500 align-middle" />
              {activity}
            </p>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSend();
        }}
        className="border-t border-ink-200 px-5 py-3 dark:border-ink-800"
      >
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            rows={1}
            disabled={busy}
            placeholder={busy ? activity ?? "Working…" : "Tell the consultant about your trip"}
            className="thin-scroll max-h-40 min-h-[2.6rem] flex-1 resize-y rounded-md border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 placeholder:text-ink-400 focus:border-petrol-500 focus:outline-none focus:ring-1 focus:ring-petrol-500 disabled:opacity-60 dark:border-ink-800 dark:bg-ink-950 dark:text-ink-100"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-md bg-petrol-700 px-4 py-2 text-sm font-medium text-white transition hover:bg-petrol-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-petrol-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}

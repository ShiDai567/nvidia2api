"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cx } from "@/components/ui";

/** 轻量 Markdown 渲染（GFM），暗色控制台风格。 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cx("md-body text-sm leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (p) => <h1 className="mb-2 mt-3 text-lg font-semibold text-gray-100 first:mt-0" {...p} />,
          h2: (p) => <h2 className="mb-2 mt-3 text-base font-semibold text-gray-100 first:mt-0" {...p} />,
          h3: (p) => <h3 className="mb-1.5 mt-3 text-sm font-semibold text-gray-100 first:mt-0" {...p} />,
          h4: (p) => <h4 className="mb-1.5 mt-2 text-sm font-semibold text-gray-200 first:mt-0" {...p} />,
          p: (p) => <p className="my-2 whitespace-pre-wrap first:mt-0 last:mb-0" {...p} />,
          a: (p) => (
            <a
              className="text-blue-400 underline underline-offset-2 hover:text-blue-300"
              target="_blank"
              rel="noreferrer"
              {...p}
            />
          ),
          ul: (p) => <ul className="my-2 list-disc space-y-1 pl-5" {...p} />,
          ol: (p) => <ol className="my-2 list-decimal space-y-1 pl-5" {...p} />,
          li: (p) => <li className="marker:text-gray-500" {...p} />,
          blockquote: (p) => (
            <blockquote
              className="my-2 border-l-2 border-white/20 pl-3 text-gray-400"
              {...p}
            />
          ),
          hr: () => <hr className="my-3 border-white/10" />,
          table: (p) => (
            <div className="my-2 overflow-x-auto rounded-lg border border-white/10">
              <table className="w-full border-collapse text-xs" {...p} />
            </div>
          ),
          thead: (p) => <thead className="bg-white/[0.04]" {...p} />,
          th: (p) => (
            <th className="border-b border-white/10 px-2.5 py-1.5 text-left font-medium text-gray-300" {...p} />
          ),
          td: (p) => <td className="border-b border-white/5 px-2.5 py-1.5 align-top text-gray-300" {...p} />,
          code: ({ className: cls, children, ...rest }) => {
            const isBlock = /language-/.test(cls ?? "") || String(children).includes("\n");
            if (isBlock) {
              return (
                <code className={cx("block font-mono text-xs text-gray-200", cls)} {...rest}>
                  {children}
                </code>
              );
            }
            return (
              <code
                className="rounded bg-white/10 px-1 py-0.5 font-mono text-[12px] text-amber-200"
                {...rest}
              >
                {children}
              </code>
            );
          },
          pre: (p) => (
            <pre
              className="my-2 overflow-x-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-xs"
              {...p}
            />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import mermaid from 'mermaid'

mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'loose',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
})

function normalizeOcrMarkdown(text: string) {
  return (text || '')
    .replace(/\[→:([^\]]*)\]/g, '**→$1**')
    .replace(/\[重点:([^\]]*)\]/g, '**重点:$1**')
    .replace(/\[批注:([^\]]*)\]/g, '*批注:$1*')
    .replace(/\[圈选:([^\]]*)\]/g, '**圈选:$1**')
}

function resolveMarkdownImagePath(src: string | undefined, noteFilePath?: string | null) {
  const raw = (src || '').trim()
  if (!raw) return ''
  if (/^(https?:|data:image|blob:)/i.test(raw) || raw.startsWith('/api/')) return raw

  let path = raw
  if (!path.startsWith('/')) {
    const base = (noteFilePath || '').replace(/\\/g, '/')
    const directory = base.slice(0, Math.max(0, base.lastIndexOf('/')))
    path = `${directory}/${raw}`
  }

  const segments = path.split('/')
  const resolved: string[] = []
  for (const segment of segments.slice(1)) {
    if (!segment || segment === '.') continue
    if (segment === '..') resolved.pop()
    else resolved.push(segment)
  }
  path = `/${resolved.join('/')}`
  return `/api/files/markdown-image?path=${encodeURIComponent(path)}`
}

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    const id = `brain-mm-${Math.random().toString(36).slice(2, 10)}`
    mermaid
      .render(id, code)
      .then((result) => {
        if (cancelled || !ref.current) return
        const svg = typeof result === 'string' ? result : result.svg
        ref.current.innerHTML = svg
        setError('')
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [code])

  if (error) {
    return (
      <div className="my-3 rounded-lg border border-rose/20 bg-rose/5 p-3">
        <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-rose/80">
          Mermaid 解析失败
        </div>
        <pre className="whitespace-pre-wrap break-words font-mono text-xs text-rose/80">{code}</pre>
      </div>
    )
  }
  return (
    <div
      ref={ref}
      className="my-3 overflow-auto rounded-lg border border-white/10 bg-white/95 p-3"
    />
  )
}

export function MarkdownView({
  content,
  mermaidCode,
  noteFilePath,
  className = '',
}: {
  content: string
  mermaidCode?: string | null
  className?: string
  noteFilePath?: string | null
}) {
  const markdown = useMemo(() => normalizeOcrMarkdown(content || ''), [content])

  return (
    <div className={`prose-invert space-y-3 text-sm leading-relaxed text-starlight/90 ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-2 mt-4 border-b border-white/10 pb-1 font-display text-lg text-starlight first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-4 font-display text-base text-starlight first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1 mt-3 font-display text-sm text-starlight first:mt-0">{children}</h3>
          ),
          p: ({ children }) => <p className="leading-relaxed">{children}</p>,
          ul: ({ children }) => <ul className="ml-4 list-disc space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="ml-4 list-decimal space-y-1">{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-flux/40 pl-3 text-dust">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-lg border border-white/10">
              <table className="w-full text-left text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-b border-white/10 bg-white/5 px-2 py-1.5 font-medium text-starlight">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-white/5 px-2 py-1.5 align-top text-starlight/80">{children}</td>
          ),
          code: ({ className: codeClass, children }) => {
            const lang = /language-([\w-]+)/.exec(codeClass || '')
            if (lang && lang[1] === 'mermaid') {
              return <MermaidBlock code={String(children).replace(/\n$/, '')} />
            }
            return (
              <code className="rounded bg-white/5 px-1 py-0.5 font-mono text-xs text-flux">
                {children}
              </code>
            )
          },
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-lg border border-white/10 bg-void-500/40 p-3 font-mono text-xs">
              {children}
            </pre>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-flux underline decoration-flux/40 underline-offset-2 hover:text-azure"
            >
              {children as ReactNode}
            </a>
          ),
          img: ({ src, alt }) => (
            <img
              src={resolveMarkdownImagePath(src, noteFilePath)}
              alt={alt ?? ''}
              className="my-2 max-w-full rounded-lg border border-white/10"
            />
          ),
          hr: () => <hr className="my-4 border-white/10" />,
        }}
      >
        {markdown}
      </ReactMarkdown>
      {mermaidCode && mermaidCode.trim() && <MermaidBlock code={mermaidCode.trim()} />}
    </div>
  )
}

// Where a sentence comes from: each source's passage with the fact's words highlighted, the newer source above an
// out-of-date one, both sides of a dispute, and the fact's history over time.

import { ArrowUpRight, X } from '@phosphor-icons/react'
import type { ReactNode, Ref } from 'react'
import type { Source } from './api'
import { FactHistory } from './FactHistory'
import { focusFact, type Sentence } from './state'
import { formatDate, highlight, kindLabel, plural } from './text'

function Passage({ source }: { source: Source }) {
  const text = source.passage ?? source.fact ?? ''
  const { pieces, whole } = highlight(text, source.fact)
  return (
    <blockquote className="text-[15px] leading-[1.65] text-ink">
      {whole ? (
        <span className="rounded-[3px] bg-marker-soft box-decoration-clone px-[0.15em]">{text}</span>
      ) : (
        pieces.map((p, i) => (p.hit ? <mark key={i} className="marker text-ink">{p.text}</mark> : <span key={i}>{p.text}</span>))
      )}
    </blockquote>
  )
}

function status(source: Source): ReactNode {
  if (source.stale) return <span className="text-proof">Out of date</span>
  if (!source.current) return <span className="text-faint">Held until {formatDate(source.valid_to)}</span>
  return null
}

export function SourceCard({ source, label, labelTone = 'muted' }: { source: Source; label?: ReactNode; labelTone?: 'muted' | 'cobalt' | 'proof' | 'amber' }) {
  const tones = { muted: 'text-muted', cobalt: 'text-cobalt', proof: 'text-proof', amber: 'text-amber' }
  const state = status(source)
  return (
    <article className="rounded-[18px] bg-paper-2 p-4 sm:p-5">
      {label && <p className={`mb-3 text-[13.5px] font-semibold ${tones[labelTone]}`}>{label}</p>}
      <p className="text-[13px] text-muted">
        {kindLabel(source.kind)}
        {source.date && <> · {formatDate(source.date)}</>}
        {state && <> · {state}</>}
      </p>
      <h3 className="mt-1 text-[16px] leading-snug font-semibold tracking-[-0.01em] text-ink">{source.title ?? 'Untitled document'}</h3>
      <div className="mt-3">
        <Passage source={source} />
      </div>
      {source.removed && <p className="mt-2 text-[13px] text-faint">This passage has since been removed from the page.</p>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        {source.url ? (
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded text-[13.5px] font-semibold whitespace-nowrap text-cobalt hover:text-cobalt-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
          >
            Open the original <ArrowUpRight size={13} weight="bold" />
          </a>
        ) : (
          <span />
        )}
        <code className="font-mono text-[11px] text-faint" title="Fact id">
          {source.fact_id}
        </code>
      </div>
    </article>
  )
}

const headline: Record<string, { text: (s: Sentence) => string; tone: string }> = {
  verified: { text: (s) => `Verified against ${plural(s.sources.length, 'source')}`, tone: 'text-cobalt' },
  stale: { text: () => 'Out of date', tone: 'text-proof' },
  disputed: { text: () => 'Two sources disagree', tone: 'text-amber' },
  unsupported: { text: (s) => (s.error ? 'Removed: the check could not run' : 'Removed: nothing in the graph backs it'), tone: 'text-muted' },
}

function Body({ ws, sentence }: { ws: string; sentence: Sentence }) {
  const focus = focusFact(sentence)
  let sources: ReactNode
  switch (sentence.verdict) {
    case 'stale': {
      const old = sentence.sources.filter((f) => !f.current)
      sources = (
        <div className="space-y-3">
          {sentence.newer.map((n) => (
            <SourceCard key={n.fact_id} source={n} label={`Replaced on ${formatDate(n.valid_from)}`} labelTone="cobalt" />
          ))}
          {(old.length ? old : sentence.sources).map((f) => (
            <SourceCard key={f.fact_id} source={f} label="What the answer cited" labelTone="proof" />
          ))}
        </div>
      )
      break
    }
    case 'disputed':
      sources = (
        <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
          {sentence.sources.slice(0, 1).map((f) => (
            <SourceCard key={f.fact_id} source={f} label="This sentence" labelTone="amber" />
          ))}
          {sentence.conflicting.map((f) => (
            <SourceCard key={f.fact_id} source={f} label="Disagrees" labelTone="amber" />
          ))}
        </div>
      )
      break
    case 'unsupported':
      sources = sentence.sources.length ? (
        <div className="space-y-3">
          <p className="text-[15px] leading-relaxed text-muted">It cited this fact, which does not say what the sentence says.</p>
          {sentence.sources.map((f) => (
            <SourceCard key={f.fact_id} source={f} />
          ))}
        </div>
      ) : (
        <p className="text-[15px] leading-relaxed text-muted">It cited no fact in the graph, so it was not shown.</p>
      )
      break
    default:
      sources = (
        <div className="space-y-3">
          {sentence.sources.map((f) => (
            <SourceCard key={f.fact_id} source={f} />
          ))}
        </div>
      )
  }

  return (
    <div className="space-y-8">
      {sources}
      {focus && sentence.verdict !== 'unsupported' && focus.predicate !== 'document' && (
        <section aria-labelledby="fact-history">
          <h3 id="fact-history" className="text-[15px] font-semibold text-ink">
            Fact history
          </h3>
          <p className="mt-1 mb-4 text-[13.5px] text-muted">Every source on this subject, over the months it held.</p>
          <FactHistory ws={ws} factId={focus.fact_id} />
        </section>
      )}
    </div>
  )
}

export function SourcePanel({ ws, sentence, onClose, ref }: { ws: string; sentence: Sentence; onClose: () => void; ref?: Ref<HTMLDivElement> }) {
  const head = headline[sentence.verdict ?? 'verified']
  return (
    <div ref={ref} tabIndex={-1} className="outline-none">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className={`text-[14px] font-semibold ${head.tone}`}>{head.text(sentence)}</p>
          <p id="panel-title" className="mt-2 text-[18px] leading-snug tracking-[-0.01em] text-pretty text-ink">
            {sentence.text}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close sources"
          className="-mt-1 -mr-1 grid size-9 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-paper-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-cobalt"
        >
          <X size={17} weight="bold" />
        </button>
      </header>
      <div className="mt-6">
        <Body ws={ws} sentence={sentence} />
      </div>
    </div>
  )
}

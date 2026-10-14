import type { ComponentProps, ReactNode } from 'react'

export const REPO_URL = 'https://github.com/sushanshetty1/canon'

/** Three lines of a page: the first checked (cobalt), the second plain, the last out of date (proof red). */
export function Mark({ className = 'h-4 w-auto' }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 30" className={className} aria-hidden="true">
      <rect x="0" y="0" width="40" height="7" rx="3.5" fill="var(--cobalt)" />
      <rect x="0" y="11.5" width="30" height="7" rx="3.5" fill="currentColor" />
      <rect x="0" y="23" width="20" height="7" rx="3.5" fill="var(--proof)" />
    </svg>
  )
}

export function Wordmark({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <Mark className="h-[15px] w-auto" />
      <span className="font-display text-[19px] font-semibold tracking-[-0.035em]">Canon</span>
    </span>
  )
}

export function Container({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`mx-auto w-full max-w-[1240px] px-6 sm:px-10 lg:px-14 ${className}`}>{children}</div>
}

/** A section on its own sheet. `tone` picks paper or night. */
export function Slab({ id, tone = 'paper', className = '', children }: { id?: string; tone?: 'paper' | 'night' | 'paper-2'; className?: string; children: ReactNode }) {
  const tones = { paper: 'bg-paper text-ink', 'paper-2': 'bg-paper-2 text-ink', night: 'bg-night text-paper' }
  return (
    <section id={id} className={`slab ${tones[tone]} ${className}`}>
      {children}
    </section>
  )
}

type ButtonProps = ComponentProps<'a'> & { variant?: 'ink' | 'line' | 'cobalt' | 'line-night' }

export function Button({ variant = 'ink', className = '', children, ...rest }: ButtonProps) {
  const base =
    'group inline-flex h-12 items-center justify-center gap-2.5 whitespace-nowrap rounded-full px-6 text-[15px] font-semibold tracking-[-0.01em] transition-[background-color,color,box-shadow,transform] duration-200 ease-out active:translate-y-px'
  const styles = {
    ink: 'bg-ink text-paper hover:bg-[#23252d]',
    cobalt: 'bg-cobalt text-paper hover:bg-cobalt-deep',
    line: 'text-ink shadow-[inset_0_0_0_1.5px_var(--line-strong)] hover:shadow-[inset_0_0_0_1.5px_var(--ink)]',
    'line-night': 'text-paper shadow-[inset_0_0_0_1.5px_var(--night-line)] hover:shadow-[inset_0_0_0_1.5px_var(--paper)]',
  }
  return (
    <a className={`${base} ${styles[variant]} ${className}`} {...rest}>
      {children}
    </a>
  )
}

export type Verdict = 'checking' | 'verified' | 'stale' | 'disputed' | 'unsupported'

const verdictLabel: Record<Verdict, string> = {
  checking: 'Checking',
  verified: 'Verified',
  stale: 'Out of date',
  disputed: 'Disputed',
  unsupported: 'Unsupported',
}

const verdictClass: Record<Verdict, string> = {
  checking: 'bg-paper-2 text-faint',
  verified: 'bg-cobalt text-paper',
  stale: 'bg-proof text-paper',
  disputed: 'bg-amber-soft text-amber',
  unsupported: 'bg-paper-2 text-muted',
}

export function VerdictTag({ verdict, className = '' }: { verdict: Verdict; className?: string }) {
  return (
    <span className={`inline-flex h-6 shrink-0 items-center rounded-full px-2.5 font-mono text-[11.5px] font-semibold whitespace-nowrap ${verdictClass[verdict]} ${className}`}>
      {verdictLabel[verdict]}
    </span>
  )
}

export function SectionTitle({ title, lede, tone = 'paper' }: { title: ReactNode; lede?: ReactNode; tone?: 'paper' | 'night' }) {
  return (
    <div className="max-w-[760px]">
      <h2 className="display text-[40px] text-balance sm:text-[56px]">{title}</h2>
      {lede && <p className={`mt-5 max-w-[600px] text-[18px] leading-relaxed text-pretty ${tone === 'night' ? 'text-[#a3a8b3]' : 'text-muted'}`}>{lede}</p>}
    </div>
  )
}

import { ArrowUpRight } from '@phosphor-icons/react'
import { Button, Container, REPO_URL, Slab, Wordmark } from '../ui'

const links = [
  ['How it checks', '#check'],
  ['Product', '#product'],
  ['Demo company', '#company'],
  ['GitHub', REPO_URL],
  ['FalkorDB', 'https://www.falkordb.com'],
]

export function Closing() {
  return (
    <Slab tone="paper" className="ruled">
      <Container className="py-24 sm:py-32">
        <h2 className="display max-w-[980px] text-[44px] text-balance sm:text-[72px]">
          Stop answering from <span className="text-proof line-through decoration-[0.07em]">last quarter's</span> handbook.
        </h2>
        <div className="mt-10">
          <Button href={REPO_URL} variant="ink">
            View on GitHub <ArrowUpRight size={16} weight="bold" />
          </Button>
        </div>
      </Container>
      <div className="border-t border-line">
        <Container className="flex flex-col gap-8 py-10 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <Wordmark className="text-ink" />
            <p className="mt-3 max-w-[22rem] text-[14px] leading-relaxed text-muted">
              Built for the FalkorDB Hackathon 2026, Track 03. Open source under Apache-2.0. Made with help from Claude Code, as the README explains.
            </p>
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-x-12 gap-y-3 sm:grid-cols-3">
            {links.map(([label, href]) => (
              <a key={label} href={href} className="text-[14.5px] text-muted transition-colors hover:text-ink">
                {label}
              </a>
            ))}
          </nav>
        </Container>
      </div>
    </Slab>
  )
}

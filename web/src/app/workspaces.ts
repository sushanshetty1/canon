import type { ServerWorkspace } from './account'

export type Workspace = {
  slug: string
  name: string
  label: string
  suggestions: string[]
  own?: boolean
  repo?: string | null
  /** Made from a private repository. */
  private?: boolean
  role?: string | null
}

export const WORKSPACES: Workspace[] = [
  {
    slug: 'posthog',
    name: 'PostHog',
    label: 'PostHog',
    suggestions: ['Which team owns the MCP server?', 'Who owns notebooks?', 'How do I escalate a support ticket?'],
  },
  {
    slug: 'demo',
    name: 'Kestrel',
    label: 'Kestrel (demo)',
    suggestions: ['Who owns session replay?', 'Can we deploy on Fridays?', 'Who owns notebooks?'],
  },
]

/** A workspace the server lists, in the shape the screens use. Public ones keep their written suggestions. */
export function fromServer(w: ServerWorkspace): Workspace {
  const known = WORKSPACES.find((k) => k.slug === w.slug)
  if (known && w.public) return known
  return {
    slug: w.slug,
    name: w.repo ?? w.name,
    label: w.repo ?? w.name,
    suggestions: w.suggestions ?? [],
    own: !w.public,
    repo: w.repo,
    private: !!w.private,
    role: w.role,
  }
}

const KEY = 'canon-workspace'

export function savedWorkspace(): Workspace {
  try {
    const raw = window.localStorage.getItem(KEY)
    const known = WORKSPACES.find((w) => w.slug === raw)
    if (known) return known
    const saved = raw?.startsWith('{') ? (JSON.parse(raw) as Workspace) : null
    return saved?.slug ? saved : WORKSPACES[0]
  } catch {
    return WORKSPACES[0]
  }
}

export function saveWorkspace(w: Workspace) {
  try {
    window.localStorage.setItem(KEY, w.own ? JSON.stringify(w) : w.slug)
  } catch {
    // private window: the choice lasts this visit
  }
}

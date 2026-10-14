export type Workspace = { slug: string; name: string; label: string; suggestions: string[] }

export const WORKSPACES: Workspace[] = [
  {
    slug: 'demo',
    name: 'Kestrel',
    label: 'Kestrel (demo)',
    suggestions: ['Who owns session replay?', 'Can we deploy on Fridays?', 'Who owns notebooks?'],
  },
  {
    slug: 'posthog',
    name: 'PostHog',
    label: 'PostHog',
    suggestions: ['Who owns notebooks?', 'Who owns feature flags?', 'How long are session recordings kept?'],
  },
]

const KEY = 'canon-workspace'

export function savedWorkspace(): Workspace {
  try {
    const slug = window.localStorage.getItem(KEY)
    return WORKSPACES.find((w) => w.slug === slug) ?? WORKSPACES[0]
  } catch {
    return WORKSPACES[0]
  }
}

export function saveWorkspace(w: Workspace) {
  try {
    window.localStorage.setItem(KEY, w.slug)
  } catch {
    // private window: the choice lasts this visit
  }
}

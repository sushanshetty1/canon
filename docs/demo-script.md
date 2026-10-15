# Demo video script

About 3 minutes. Record at 1440 wide on https://canon.sushans.dev, signed in with GitHub. Speak plainly; every number
below is real and on screen.

Before recording:
- Ask the three suggested questions once, so their answers are cached and stream instantly.
- Have a small repository of your own ready for the New workspace step (or skip that step).
- Close other tabs; turn off notifications.

## 1. The problem (0:00 to 0:20)

**Screen:** the landing page hero, the knowledge timeline animating.

> Every company brain can find a page and cite it. None of them checks whether the page is still true. PostHog's
> handbook says the PostHog AI team owns the MCP server. It moved to another team in September. Ask a normal
> assistant and you get the old answer, with a confident citation.

## 2. Ask, checked sentence by sentence (0:20 to 0:55)

**Screen:** /app, PostHog workspace. Click the suggestion "Which team owns the MCP server?"

> Canon read PostHog's handbook, its ownership history, 28,000 pull requests, its issues and its forum into one
> FalkorDB graph. Every sentence of the answer is checked against that graph before you see it.

**Action:** click the first sentence. The source panel opens.

> Verified against the ownership-map commit from September 17, and the team's own page. Below it, this fact's
> history: PostHog AI, Signals, Self-Driving, then Context and MCP. The graph knows which one holds today. The
> model only writes the sentence.

**Action:** point at "2 sentences removed".

> Two sentences the model wrote were removed, because nothing in the graph backs them.

## 3. A dispute (0:55 to 1:10)

**Action:** New question, click "How do I escalate a support ticket?"

> Two of PostHog's own pages disagree on where a ticket goes. Canon does not pick one. It marks the sentence
> disputed and shows both sources.

## 4. The fix queue: getting work done (1:10 to 1:45)

**Screen:** Fix queue.

> When a page says something the graph knows has changed, Canon drafts the fix. Here is the handbook line, struck,
> and the correction, checked against the newer fact before it reaches you. It goes to the team that owns the area,
> because the ownership map says so.

**Action:** Approve and file, choose your own repository, show the created GitHub issue.

> A person approves, and Canon files it as a GitHub issue.

## 5. Who knows and the bus factor (1:45 to 2:15)

**Screen:** Bus factor.

> Who actually knows each area comes from what people did: wrote, reviewed, decided, said. The bus factor is a
> maximum flow in FalkorDB, from each area through its evidence to the people who hold it. 36 PostHog areas rest on
> one person. Pipeline sources rests on one engineer and 3,422 pull requests.

**Action:** click an area to open Who knows, then a person to show their evidence.

## 6. Decisions and catch me up (2:15 to 2:35)

**Screen:** Decisions, then Catch me up; drag the range back to September 1.

> Every design doc from proposal to replacement. And if you were away: every ownership change, decision and newly
> stale page since the day you left, summarised and checked the same way.

## 7. Your own company (2:35 to 2:55)

**Screen:** Sources, then Connect.

> Canon reads docs, tickets and chats: GitHub repositories, private and organisation ones too, Slack, Notion,
> Linear, Jira, Confluence and files. It reads them again every hour, so the answers follow what changed.

**Action (optional):** New workspace, pick a repository, show the drawing as it reads.

## 8. Close (2:55 to 3:05)

**Screen:** README's Measured table.

> On 56 PostHog questions, with the same model, Canon answered 98 percent correctly and never stated an
> out-of-date answer as current. On the 13 questions where the handbook is out of date, plain search got none.
> Canon, on FalkorDB. Open source, and live at canon.sushans.dev.

# Cited is not the same as true: building a company brain that checks itself

PostHog's handbook has a page about its AI products. It was last edited on September 23, and it says the PostHog AI team owns the MCP server. Six days earlier, PostHog's own feature ownership map moved the MCP server to a team called Context & MCP. Before that it had belonged to Self-Driving, before that to Signals, and before that to PostHog AI, which is the team the page still names.

Nobody did anything wrong. Someone edited the page for another reason and didn't touch that line. Every company has hundreds of lines like it, and every company-brain product I tried will happily quote one back to you, with a citation, as if a citation meant the sentence was still true.

That gap is what I spent the FalkorDB hackathon on. Canon reads a company's docs, tickets and chats into one graph that knows when each fact held, and it checks every sentence of an answer against that graph before you see it.

## Search finds words. It can't tell you what replaced them.

The standard pipeline is search, then summarise. Find the passages that look most like the question, hand them to a model, ask for an answer with citations. It works well until two passages disagree, and then it has no way to know which one is current. The handbook page and the ownership map both "match" the question. One is right.

You can't fix that with a better prompt. The information isn't in the text. "This replaced that, on this date" is a relationship between two facts, and relationships are what a graph is for.

So the core of Canon is small:

- every fact is a node with the dates it held, linked to the passage it came from and the document that passage is in;
- when a newer fact replaces an older one, the two are joined by a `SUPERSEDED_BY` edge;
- when two current sources disagree, they're joined by `CONTRADICTS`.

Then "is this still true?" stops being a judgement call and becomes a walk:

```cypher
MATCH (f:Fact) WHERE f.id IN $ids
MATCH (f)-[:SUPERSEDED_BY*1..6]->(n:Fact) WHERE NOT (n)-[:SUPERSEDED_BY]->()
RETURN f.id, n.id
```

If the walk goes anywhere, the fact has been replaced, and `n` is what holds now.

## The model writes; the graph decides

I was strict about one rule from the first hour: no model gets to decide whether something is current. Models are good at writing sentences and bad at knowing what day it is.

When you ask Canon a question, retrieval finds candidate facts with a full-text index, expands through the people, teams and areas the question names, and follows `SUPERSEDED_BY` to whatever is current. A model then drafts the answer one sentence at a time, and each sentence has to cite the fact ids it relies on.

Before a sentence reaches you, it gets a verdict:

- **Verified:** a source states it and nothing newer replaced it.
- **Out of date:** a newer fact replaced it. Canon shows the newer one in its place, with the date it changed.
- **Disputed:** two current sources disagree. Canon shows both instead of picking one.
- **Removed:** it cited nothing real, so it isn't shown.

A small model does one narrow job in that check: confirm the sentence actually says what its cited facts say. Whether those facts are current is a graph query.

## Where the facts come from

The hackathon allows public data only, so I needed a real company that works in public. PostHog was close to perfect. Its handbook and team pages are open, its design docs (RFCs) are open, and its issues, pull requests and forum are all public. Best of all, it keeps a file called `useFeatureOwnership.tsx`, mapping each product area to the team that owns it, under version control.

That file's git history became the backbone. I read every one of its 72 versions and turned each owner change into a dated fact: this area was owned by this team from this commit until that one. No model involved, and impossible to argue with. It's the most authoritative source in the graph.

Prose is messier. For the handbook, team pages and design docs, a model extracts facts into a closed vocabulary (`owned_by`, `leads`, `decided`, `process`, `policy`, `uses`, `contact_for`). The closed vocabulary matters more than it looks. If the model could invent predicates, I'd never be able to tell that two facts are about the same thing, and supersession would have nothing to link. Extracting 1,500 passages cost $0.31 on Claude Haiku, cached so a rebuild costs nothing.

Then authority does the rest. The ownership map outranks a design doc, a design doc outranks a handbook page, and a handbook page outranks a ticket or a chat message. A handbook page that names an owner *after* the ownership map already changed it is out of date from the day it was written. That single rule found 13 stale ownership statements on 5 real PostHog pages. The MCP server line was one of them.

## The first version flagged 353 disputes, and almost none were real

The first full run linked 353 pairs of facts as disputed. I was briefly pleased, then I read them.

"Each team decides whether its support hero handles community questions" was flagged as contradicting "Community questions are routed to team Slack channels by topic". They don't contradict. They're two true sentences about one topic. My linker treated every topic like ownership, where one value replaces another, but a process can have ten true statements at once.

The fix was to admit that some questions are about meaning. Ownership and decisions stay deterministic. For free-text process and policy facts, a small model reads all the current statements on a topic and names only the pairs that cannot both be true, and the graph stores its answer as an edge. The first attempt at that still flagged pairs where the model's own explanation said "this is not a true conflict", so it now has to answer `cannot_both_hold` explicitly. 353 became 1, and that one is real: two PostHog pages give different routes for escalating a support ticket.

## Who knows, and what happens if they leave

Once people are in the graph, two more questions get easy.

**Who actually knows an area?** Not job titles. Canon weighs what people did: wrote, reviewed, decided or said, with recent work counting more. Over 28,099 PostHog pull requests from the last six months, that gives a ranked list with the evidence behind every name.

**How many people could still answer for it if the rest left?** That's a flow problem, and FalkorDB has `algo.maxFlow`. Each area gets a small network: the area, then its evidence documents with capacity 1 each, then the people who worked on them, then a sink. Because each pull request carries one unit, three people who only reviewed the same pull request count once. The maximum flow is the number of people who hold the area through work of their own. The minimum cut, which I read from the residual network myself because the procedure returns only the edges carrying flow, names what the area hinges on.

I want to be honest about the result on PostHog: for every area, the flow came out equal to the number of experts. Everyone above the evidence bar had written their own pull requests, so nobody's knowledge depended only on someone else's. The model is right, and the tests on hand-built examples show it cutting below the head count when it should. PostHog's engineers just don't work in a way that triggers it. 36 areas still rest on a single person, which is the useful finding anyway.

## Getting work done, not just answering

Answering is half the job. If Canon knows a page is wrong, it should help fix it.

So every stale line becomes a fix. Canon drafts the corrected sentence from the newer fact, then runs that draft through the same check as any answer, and throws it away unless it comes back verified. The fix is routed to the team that owns the area the page is about, because the ownership map says so. A person approves it, and Canon files a GitHub issue with the old line, the new one and the evidence link. Nothing is filed without a human saying yes.

## Did it work?

I wrote 56 questions about PostHog whose answers come from dated records, never from a model: who owns an area now, who owned it before, who leads a team. 13 of them are traps, where a handbook page still names an owner the ownership map has since changed.

Three systems answered every question with the same model, Claude Haiku, and a separate model graded them:

| | Canon | Same passages, no graph | Search and summarise |
| --- | --- | --- | --- |
| Correct | 98% | 95% | 20% |
| Out-of-date answer stated as current | 0% | 2% | 5% |
| Stale traps right | 13 of 13 | 10 of 13 | 0 of 13 |

The middle column is the fair fight. It gets exactly the passages Canon retrieved, including the ones Canon only found by following the graph to the current fact. It loses only the graph's account of time and the check. On ordinary questions that's close. On the traps, where the handbook is wrong, it isn't.

Where Canon lost: on "who owned this before" questions it scored 83% against the baseline's 100%, because the check removed one true sentence about history as unsupported. Every question, answer and grade is in the repo.

## Things I'd tell myself on day one

- **A citation proves where a sentence came from, not whether it's still true.** Those are different questions, and only the second one needs time.
- **Make the model's job small.** Every time I let a model decide something the graph could decide, it got worse and harder to explain.
- **Closed vocabularies beat clever extraction.** You can't link facts you can't compare.
- **Read your own output before you celebrate a number.** 353 disputes looked like a feature until I read ten of them.
- **FalkorDB has sharp edges worth knowing.** In 6.0.2, an aggregation grouped by a value that can be null took the server down, so every grouping key in Canon is wrapped in `coalesce()`. `shortestPath` only works inside `WITH` or `RETURN`. Neither slowed me down once I knew. Meanwhile `GRAPH.COPY` gave every parallel workstream its own copy of the demo graph, and a Redis `DUMP` ships a pre-built 10 MB graph with the deployment so the live site boots ready.

## Try it

Canon is live at [canon.sushans.dev](https://canon.sushans.dev), running on PostHog's public record. Ask "Which team owns the MCP server?" and click the answer to see its history. Then open the fix queue. You can sign in with GitHub and point it at your own repository, and connect Slack, Notion, Linear, Jira or Confluence.

The code is at [github.com/sushanshetty1/canon](https://github.com/sushanshetty1/canon), Apache-2.0, built for the FalkorDB hackathon, Track 03. I used Claude Code as a coding assistant throughout, and the README says so.

If your company has a handbook, it has a line like the MCP server one. The interesting part isn't finding it. It's knowing that it's wrong.

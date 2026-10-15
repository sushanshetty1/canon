# Demo video

**File:** attached to the [`demo-video` release](https://github.com/sushanshetty1/canon/releases/tag/demo-video) (`canon-demo.mp4`, 2:41, 1080p). Source: [`video/`](../video).

## Title

Canon: a company brain that checks every answer against what's true today

## Description

Every company brain can find a page and cite it. None of them checks whether that page is still true. Canon does.

Canon reads a company's docs, tickets and chats into one FalkorDB graph that knows when each fact held. Before you see an answer, every sentence is checked against that graph: verified, out of date, disputed, or removed. When a page says something that has since changed, Canon drafts the fix and routes it to the team that owns it.

In this video, on PostHog's public handbook, design docs, issues, pull requests and forum:
- Ask, with every sentence checked and its source one click away
- How the check walks the graph, and the Cypher that runs it
- The fix queue, filing a GitHub issue after a person approves it
- Who actually knows each area, and the bus factor as a maximum flow (algo.maxFlow)
- Decisions, catch me up, and the sources Canon connects to: GitHub, Slack, Notion, Linear, Jira, Confluence and files
- The benchmark: 56 PostHog questions with known answers. Canon answered 98% correctly and stated no out-of-date answer as current. On the 13 questions where the handbook is out of date, Canon got 13 and search-and-summarise got 0.

Live: https://canon.sushans.dev
Code: https://github.com/sushanshetty1/canon

Built for the FalkorDB Hackathon 2026, Track 03 (Company Brain).

Chapters:
0:00 The problem
0:19 The idea: a graph that knows when each fact held
0:30 How the check walks the graph
0:51 Ask, checked sentence by sentence
1:12 When two pages disagree
1:22 The fix queue
1:35 Who knows, and the bus factor
1:55 Decisions and catch me up
2:04 Your own sources
2:18 The benchmark
2:33 Canon

# Bus factor

How many people hold an area's knowledge **independently**, and what the area hinges on. It is a maximum flow,
computed by FalkorDB's `algo.maxFlow`, and its minimum cut. The code is
[`server/src/canon/people/bus_factor.py`](../server/src/canon/people/bus_factor.py).

## The network

Each area gets its own three-layer network. It is built, run and removed in turn, because documents and people
are shared between areas.

```
(:Area) -[:FLOW {cap: 1}]-> (:Document) -[:FLOW {cap: 1000000}]-> (:Person) -[:FLOW {cap: 1}]-> (:Sink)
```

- **People** know the area well enough to answer for it. Their `KNOWS` score is at least 3, and at least a quarter
  of the area's top score. See [`expertise.py`](../server/src/canon/people/expertise.py): it weighs decided 4,
  wrote 3, reviewed 2, commented 1 and owning team 2, and halves the weight every 180 days.
- **Documents** are the area's evidence that one of those people wrote, reviewed or decided. Each one carries a
  single unit, so one pull request can back one person, however many people touched it.
- A document reaches everyone who worked on it through a wide edge, so a cut never runs through it.
- Each person passes on one unit.

The maximum flow is the largest set of people who each hold the area through evidence of their own: a maximum
matching of people to documents. That is the bus factor. The minimum cut nearest the sink names what the area
hinges on. It names people wherever a person is the bottleneck, and documents where several people know the area
only through the same work.

**Example.** Alice wrote #1 and #2. Bob and Carol only reviewed #1. Three people know the area, but the flow is 2,
because #1 can back only one of Bob and Carol. The cut is {#1, Alice}.

## The Cypher

The people above the bar, per area:

```cypher
MATCH (p:Person)-[k:KNOWS]->(a:Area)
WITH a, max(k.score) AS top
MATCH (p:Person)-[k:KNOWS]->(a)
WHERE k.score >= $min_score AND k.score >= $share * top
RETURN a.slug, collect(p.handle)
```

One area's evidence layer:

```cypher
MATCH (a:Area {slug: $area})
MATCH (p:Person)-[:AUTHORED|REVIEWED|DECIDED]->(d:Document)
WHERE p.handle IN $knowers
  AND ((d)-[:ABOUT]->(a)
       OR (d.kind <> 'ownership_map' AND (d)-[:HAS]->(:Passage)<-[:STATED_IN]-(:Fact)-[:ABOUT]->(a)))
WITH a, d, collect(DISTINCT p) AS people
CREATE (a)-[:FLOW {cap: 1}]->(d)
WITH d, people
UNWIND people AS p
CREATE (d)-[:FLOW {cap: $wide}]->(p)
```

The people layer, into the sink:

```cypher
MATCH (:Area {slug: $area})-[:FLOW]->(:Document)-[:FLOW]->(p:Person)
WITH DISTINCT p
MATCH (t:Sink {id: $sink})
CREATE (p)-[:FLOW {cap: 1}]->(t)
```

The flow:

```cypher
MATCH (s) WHERE id(s) = $source
MATCH (t:Sink {id: $sink})
CALL algo.maxFlow({sourceNodes: [s], targetNodes: [t], capacityProperty: 'cap', relationshipTypes: ['FLOW']})
YIELD edges, edgeFlows, maxFlow
RETURN [e IN edges | id(e)], edgeFlows, maxFlow
```

`edges` and `edgeFlows` list only the edges that carry flow. The cut is read from the residual network. Every
`FLOW` edge keeps `cap - flow` forward and `flow` backward. The nodes that can still reach the sink form the sink's
side, and the edges into that side are the minimum cut (`sink_side_cut`). The network is then removed with
`MATCH ()-[e:FLOW]->() DELETE e`.

## What is stored

| On the graph | Meaning |
| --- | --- |
| `a.bus_factor` | The maximum flow |
| `a.knowers` | People above the bar |
| `a.evidence_docs` | Documents in the network |
| `(:Area)-[:FLOWS_TO {docs, via}]->(:Person)` | Each person in the network: how many documents they hold, and the one the flow routed to them |
| `(:Area)-[:DEPENDS_ON]->(:Person)` | People on the minimum cut |
| `(:Area)-[:HINGES_ON]->(:Document)` | Documents on the minimum cut |

`canon people <workspace>` recomputes all of it, after expertise. `canon ingest` runs it at the end.

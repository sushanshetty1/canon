"""Canon's own words name people by their public GitHub handle.

Sources keep their text as published: a passage that names someone is a quote, shown with a link to the original.
What Canon writes itself (fact sentences, drafted corrections, display names) uses the handle instead. People with
no public handle keep the name their source gives, since there is nothing else to call them.

    python -m canon.graph.privacy <workspace>
"""

import re
import sys

PEOPLE = "MATCH (p:Person) WHERE p.name IS NOT NULL AND NOT p.handle STARTS WITH 'name:' AND p.name <> p.handle RETURN p.handle, p.name"


def _pattern(name: str) -> re.Pattern:
    return re.compile(rf"(?<![\w@]){re.escape(name)}(?!\w)")


def handles_only(graph) -> dict[str, int]:
    people = [(h, n) for h, n in graph.query(PEOPLE).result_set if n and len(n) > 2]
    if not people:
        return {"people": 0, "facts": 0, "fixes": 0}
    patterns = [(_pattern(n), h) for h, n in sorted(people, key=lambda p: -len(p[1]))]
    # First names on their own are too ambiguous to replace; full names are not.
    patterns = [(p, h) for p, h in patterns if " " in p.pattern.replace("\\ ", " ")]

    def rewrite(text: str | None) -> str | None:
        if not text:
            return text
        for pattern, handle in patterns:
            text = pattern.sub(handle, text)
        return text

    changed = {"facts": [], "fixes": []}
    for fid, text in graph.query("MATCH (f:Fact) RETURN f.id, f.text").result_set:
        new = rewrite(text)
        if new != text:
            changed["facts"].append({"id": fid, "text": new})
    for xid, new_text in graph.query("MATCH (x:Fix) RETURN x.id, x.new").result_set:
        new = rewrite(new_text)
        if new != new_text:
            changed["fixes"].append({"id": xid, "new": new})
    if changed["facts"]:
        graph.query("UNWIND $rows AS r MATCH (f:Fact {id: r.id}) SET f.text = r.text", {"rows": changed["facts"]})
    if changed["fixes"]:
        graph.query("UNWIND $rows AS r MATCH (x:Fix {id: r.id}) SET x.new = r.new", {"rows": changed["fixes"]})
    graph.query("MATCH (p:Person) WHERE NOT p.handle STARTS WITH 'name:' SET p.name = p.handle")
    return {"people": len(people), "facts": len(changed["facts"]), "fixes": len(changed["fixes"])}


if __name__ == "__main__":
    from canon.graph.db import connect, workspace_graph

    print(handles_only(workspace_graph(connect(), sys.argv[1])))

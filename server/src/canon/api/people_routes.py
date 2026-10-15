"""Who knows what, and the bus factor.

- `GET /api/w/{ws}/areas` lists every area with its owner, bus factor and top people, riskiest first.
- `GET /api/w/{ws}/areas/{slug}/people` ranks the people who know an area, with their evidence and documents.
- `GET /api/w/{ws}/people/{handle}` lists the areas a person knows.

All of it is read from the graph, where `canon people <ws>` computed it.
"""

from fastapi import APIRouter, HTTPException, Request

from canon.people.bus_factor import org_view
from canon.people.views import area_people, person

router = APIRouter()


def _graph(request: Request, ws: str):
    return request.app.state.workspace(ws)


@router.get("/api/w/{ws}/areas")
def areas_route(ws: str, request: Request) -> dict:
    graph = _graph(request, ws)
    areas = org_view(graph)
    computed = bool(graph.query("MATCH (:Person)-[k:KNOWS]->(:Area) RETURN k LIMIT 1").result_set)
    return {"areas": areas, "computed": computed}


@router.get("/api/w/{ws}/areas/{slug}/people")
def area_people_route(ws: str, slug: str, request: Request) -> dict:
    found = area_people(_graph(request, ws), slug)
    if found is None:
        raise HTTPException(404, "No such area.")
    return found


@router.get("/api/w/{ws}/people/{handle}")
def person_route(ws: str, handle: str, request: Request) -> dict:
    found = person(_graph(request, ws), handle)
    if found is None:
        raise HTTPException(404, "No such person.")
    return found

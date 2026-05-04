from __future__ import annotations

import networkx as nx

from src.core.state import (
    Camera,
    CameraState,
    GameState,
    MapSpec,
    NPC,
    Position,
    WorldSpec,
)


def _direction_delta(direction: str) -> tuple[int, int]:
    return {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}[direction]


def cone_cells(world_size: int, walls: set[Position], cam: Camera) -> list[Position]:
    dx, dy = _direction_delta(
        cam.direction if isinstance(cam.direction, str) else cam.direction.value
    )
    cells: list[Position] = []
    cx, cy = cam.pos
    for i in range(1, cam.length + 1):
        x, y = cx + dx * i, cy + dy * i
        if not (0 <= x < world_size and 0 <= y < world_size):
            break
        if (x, y) in walls:
            break
        cells.append((x, y))
    return cells


def active_cone_cells(state: GameState) -> set[Position]:
    if state.map is None:
        return set()
    walls = set(state.map.walls)
    out: set[Position] = set()
    for cam in state.cameras:
        cam_state = cam.state if isinstance(cam.state, str) else cam.state.value
        if cam_state == CameraState.ACTIVE.value:
            for c in cone_cells(state.map.size, walls, cam):
                out.add(c)
    return out


def vision_cone_cells(state: GameState) -> set[Position]:
    if state.map is None:
        return set()
    walls = set(state.map.walls)
    out: set[Position] = set()
    for cam in state.cameras:
        cam_state = cam.state if isinstance(cam.state, str) else cam.state.value
        if cam_state == CameraState.HACKED.value:
            for c in cone_cells(state.map.size, walls, cam):
                out.add(c)
    return out


def walkable_neighbors(
    pos: Position, size: int, walls: set[Position], avoid: set[Position] | None = None
) -> list[Position]:
    avoid = avoid or set()
    res = []
    for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        nx_, ny_ = pos[0] + dx, pos[1] + dy
        if not (0 <= nx_ < size and 0 <= ny_ < size):
            continue
        if (nx_, ny_) in walls or (nx_, ny_) in avoid:
            continue
        res.append((nx_, ny_))
    return res


def _build_graph(size: int, walls: set[Position], avoid: set[Position]) -> nx.Graph:
    g: nx.Graph = nx.Graph()
    for x in range(size):
        for y in range(size):
            if (x, y) in walls or (x, y) in avoid:
                continue
            g.add_node((x, y))
    for x, y in list(g.nodes):
        for dx, dy in [(1, 0), (0, 1)]:
            n = (x + dx, y + dy)
            if n in g:
                g.add_edge((x, y), n)
    return g


def _manhattan(a: Position, b: Position) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def plan_path(
    start: Position,
    goal: Position,
    world: MapSpec | WorldSpec,
    avoid: set[Position] | None = None,
) -> list[Position] | None:
    walls = set(world.walls)
    g = _build_graph(world.size, walls, avoid or set())
    if start not in g:
        g.add_node(start)
        for nb in walkable_neighbors(start, world.size, walls, avoid):
            if nb in g:
                g.add_edge(start, nb)
    if goal not in g:
        g.add_node(goal)
        for nb in walkable_neighbors(goal, world.size, walls, avoid):
            if nb in g:
                g.add_edge(goal, nb)
    try:
        return nx.astar_path(g, start, goal, heuristic=_manhattan)
    except nx.NetworkXNoPath:
        return None


def count_alternative_paths(
    start: Position, goal: Position, world: MapSpec | WorldSpec, avoid: set[Position] | None = None
) -> int:
    walls = set(world.walls)
    g = _build_graph(world.size, walls, avoid or set())
    if start not in g or goal not in g:
        return 0
    try:
        opt = nx.astar_path_length(g, start, goal, heuristic=_manhattan)
    except nx.NetworkXNoPath:
        return 0
    return sum(1 for _ in nx.all_simple_paths(g, start, goal, cutoff=opt + 4))


def assess_risk(
    path: list[Position],
    state: GameState,
    npcs_known: bool,
) -> float:
    if not path or state.map is None:
        return 1.0

    walls = set(state.map.walls)
    cones = active_cone_cells(state)
    npc_set = {tuple(n.pos) for n in state.npcs if n.is_alive} if npcs_known else set()

    risk = 0.0
    optimal = _manhattan(path[0], path[-1])
    extra = max(0, len(path) - int(optimal) - 1)
    risk += 0.05 * (extra // 2)

    for p in path:
        if p in cones:
            return 1.0
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            n = (p[0] + dx, p[1] + dy)
            if n in cones and n not in walls:
                risk += 0.3
                break

        if p in npc_set:
            risk += 0.6
        else:
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                n = (p[0] + dx, p[1] + dy)
                if n in npc_set:
                    risk += 0.2
                    break

    if state.police_eta is not None:
        if len(path) >= state.police_eta - 5:
            risk += 0.5

    return max(0.0, min(1.0, risk))

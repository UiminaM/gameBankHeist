from __future__ import annotations

import asyncio
import json
import os
import random
import threading
from queue import Queue
from typing import Any

import pygame

from src.core.config import get_settings
from src.ui import colors as C

GRID_PADDING = 24
HUD_WIDTH = 380
WINDOW_W = 1100
WINDOW_H = 740
FPS = 30


def _ws_thread(url: str, payload: dict[str, Any], inbox: Queue) -> None:
    import websockets

    async def run() -> None:
        try:
            async with websockets.connect(url, max_size=4 * 1024 * 1024) as ws:
                await ws.send(json.dumps(payload))
                async for raw in ws:
                    inbox.put(json.loads(raw))
        except Exception as exc:
            inbox.put({"type": "error", "message": str(exc)})
        inbox.put({"type": "ws_closed"})

    asyncio.run(run())


def _draw_grid(screen, font, snapshot: dict[str, Any], anim_t: float) -> None:
    map_data = snapshot.get("map") or {}
    size = map_data.get("size", 10)
    grid_area = WINDOW_W - HUD_WIDTH - GRID_PADDING * 2
    grid_h = WINDOW_H - GRID_PADDING * 2
    cell = min(grid_area // size, grid_h // size)
    origin_x = GRID_PADDING
    origin_y = GRID_PADDING

    walls = {tuple(w) for w in map_data.get("walls", [])}

    for x in range(size):
        for y in range(size):
            color = C.WALL if (x, y) in walls else C.FLOOR
            rect = pygame.Rect(origin_x + x * cell, origin_y + y * cell, cell - 1, cell - 1)
            pygame.draw.rect(screen, color, rect, border_radius=4)

    vault = map_data.get("vault")
    entry = map_data.get("entry")
    exits = map_data.get("exits", [])
    chosen_exit = snapshot.get("chosen_exit")

    if vault:
        _fill_cell(screen, origin_x, origin_y, cell, vault, C.VAULT, label="V", font=font)
    if entry:
        _fill_cell(screen, origin_x, origin_y, cell, entry, C.ENTRY, label="E", font=font)
    for i, e in enumerate(exits):
        label = "X*" if chosen_exit == i else "X"
        _fill_cell(screen, origin_x, origin_y, cell, e, C.EXIT, label=label, font=font)

    cones_active = []
    for cam in snapshot.get("cameras", []):
        cells = _cone_cells_geom(cam, size, walls)
        if cam.get("state") == "active":
            cones_active.extend(cells)

    cone_surface = pygame.Surface((size * cell, size * cell), pygame.SRCALPHA)
    for c in cones_active:
        pygame.draw.rect(cone_surface, C.CONE, (c[0] * cell, c[1] * cell, cell - 1, cell - 1), border_radius=4)
    screen.blit(cone_surface, (origin_x, origin_y))

    for cam in snapshot.get("cameras", []):
        col = C.CAMERA_HACKED if cam.get("state") == "hacked" else C.CAMERA_ACTIVE
        cx = origin_x + cam["pos"][0] * cell + cell // 2
        cy = origin_y + cam["pos"][1] * cell + cell // 2
        pygame.draw.circle(screen, col, (cx, cy), max(4, cell // 4))

    if snapshot.get("npcs_visible_to_team"):
        for npc in snapshot.get("npcs", []):
            if not npc.get("is_alive", True):
                continue
            col = {
                "aggressive": C.NPC_AGGR,
                "scared": C.NPC_SCARED,
                "neutral": C.NPC_NEUTRAL,
            }.get(npc.get("archetype"), C.NPC_NEUTRAL)
            _fill_cell(screen, origin_x, origin_y, cell, npc["pos"], col, label="N", font=font, small=True)

    path = snapshot.get("current_path") or []
    if len(path) >= 2:
        pts = [(origin_x + p[0] * cell + cell // 2, origin_y + p[1] * cell + cell // 2) for p in path]
        pygame.draw.lines(screen, C.PATH[:3], False, pts, max(2, cell // 8))

    agents = snapshot.get("agents", [])
    if agents:
        team_pos = agents[0]["pos"]
        ax = origin_x + team_pos[0] * cell + cell // 2
        ay = origin_y + team_pos[1] * cell + cell // 2
        radius = max(6, cell // 3 + int(2 * (1 + 0.5 * (anim_t % 1))))
        pygame.draw.circle(screen, C.AGENT, (ax, ay), radius)
        pygame.draw.circle(screen, C.ACCENT, (ax, ay), radius, 2)


def _fill_cell(screen, ox, oy, cell, pos, color, label="", font=None, small=False) -> None:
    rect = pygame.Rect(ox + pos[0] * cell, oy + pos[1] * cell, cell - 1, cell - 1)
    pygame.draw.rect(screen, color, rect, border_radius=4)
    if label and font is not None:
        s = font.render(label, True, C.BG)
        screen.blit(s, (rect.centerx - s.get_width() // 2, rect.centery - s.get_height() // 2))


def _cone_cells_geom(cam: dict[str, Any], size: int, walls: set) -> list[tuple[int, int]]:
    deltas = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
    dx, dy = deltas.get(cam.get("direction", "N"), (0, -1))
    res = []
    cx, cy = cam["pos"]
    for i in range(1, cam.get("length", 3) + 1):
        x, y = cx + dx * i, cy + dy * i
        if not (0 <= x < size and 0 <= y < size):
            break
        if (x, y) in walls:
            break
        res.append((x, y))
    return res


def _draw_hud(screen, font, font_small, snapshot: dict[str, Any], events: list[dict[str, Any]]) -> None:
    panel_x = WINDOW_W - HUD_WIDTH
    pygame.draw.rect(screen, C.PANEL, (panel_x, 0, HUD_WIDTH, WINDOW_H))

    y = 20
    title = font.render("BANK HEIST", True, C.ACCENT)
    screen.blit(title, (panel_x + 16, y))
    y += 32

    status_lines = [
        f"phase: {snapshot.get('phase')}",
        f"turn: {snapshot.get('turn')}  difficulty: {snapshot.get('difficulty')}",
        f"seed: {snapshot.get('seed')}",
        f"police_eta: {snapshot.get('police_eta')}",
        f"casualties: {snapshot.get('casualties')}",
        f"loot_taken: {snapshot.get('loot_taken')}",
        f"alarm: {snapshot.get('alarm')}",
        f"npcs_known: {snapshot.get('npcs_visible_to_team')}",
        f"outcome: {snapshot.get('outcome')}",
    ]
    for line in status_lines:
        s = font_small.render(line, True, C.TEXT)
        screen.blit(s, (panel_x + 16, y))
        y += 22

    y += 8
    ev_title = font.render("EVENTS", True, C.TEXT)
    screen.blit(ev_title, (panel_x + 16, y))
    y += 26
    for ev in events[-22:]:
        text = f"[{ev.get('turn'):>3}] {ev.get('kind')}"
        s = font_small.render(text, True, C.TEXT_DIM)
        screen.blit(s, (panel_x + 16, y))
        y += 18


def _difficulty_menu(screen, font, font_small) -> str | None:
    options = ["easy", "medium", "hard"]
    selected = 1
    clock = pygame.time.Clock()
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return None
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_UP:
                    selected = (selected - 1) % len(options)
                if ev.key == pygame.K_DOWN:
                    selected = (selected + 1) % len(options)
                if ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return options[selected]
                if ev.key == pygame.K_ESCAPE:
                    return None
        screen.fill(C.BG)
        title = font.render("BANK HEIST — multi-agent", True, C.ACCENT)
        screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 200))
        sub = font_small.render("Выбери сложность (↑/↓, Enter)", True, C.TEXT_DIM)
        screen.blit(sub, (WINDOW_W // 2 - sub.get_width() // 2, 250))
        for i, opt in enumerate(options):
            color = C.ACCENT if i == selected else C.TEXT
            s = font.render(opt.upper(), True, color)
            screen.blit(s, (WINDOW_W // 2 - s.get_width() // 2, 320 + i * 50))
        pygame.display.flip()
        clock.tick(FPS)


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Bank Heist")
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    font = pygame.font.SysFont("Helvetica", 20, bold=True)
    font_small = pygame.font.SysFont("Helvetica", 14)

    difficulty = _difficulty_menu(screen, font, font_small)
    if difficulty is None:
        pygame.quit()
        return

    game_seed = random.randrange(1, 2**31)

    settings = get_settings()
    url = os.getenv("GATEWAY_URL", settings.gateway_url)
    inbox: Queue = Queue()
    threading.Thread(
        target=_ws_thread, args=(url, {"difficulty": difficulty, "seed": game_seed}, inbox), daemon=True
    ).start()

    snapshot: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    clock = pygame.time.Clock()
    anim_t = 0.0

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                running = False

        while not inbox.empty():
            msg = inbox.get_nowait()
            if msg.get("type") == "event":
                snapshot = msg.get("state", snapshot)
                events.append(msg.get("event", {}))
            elif msg.get("type") == "final":
                final = msg.get("state", {})
                snapshot.update(final)
                events.append({"turn": final.get("turn", 0), "kind": f"final:{final.get('outcome')}"})
            elif msg.get("type") == "error":
                events.append({"turn": 0, "kind": f"error:{msg.get('message')}"})

        screen.fill(C.BG)
        vis = dict(snapshot)
        vis.setdefault("seed", game_seed)
        _draw_grid(screen, font_small, vis, anim_t)
        _draw_hud(screen, font, font_small, vis, events)
        pygame.display.flip()
        anim_t += 0.05
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()

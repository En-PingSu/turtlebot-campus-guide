#!/usr/bin/env python3
"""Validate semantic map coordinates against the occupancy grid map.

Checks that all navigation target locations are:
1. On free space (not on a wall or unknown area)
2. Far enough from obstacles (clearance > robot_radius)

Usage:
    python3 validate_coordinates.py
    python3 validate_coordinates.py --fix  # suggest corrected coordinates
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Defaults — override via args if needed
SCRIPT_DIR = Path(__file__).parent
MAP_PGM = SCRIPT_DIR / "campus_guide_bot/campus_nav_llm/maps/my_map.pgm"
MAP_YAML_RESOLUTION = 0.05
MAP_YAML_ORIGIN = (-8.1, -8.64)
ROBOT_RADIUS = 0.175
SAFETY_MARGIN = 0.05  # extra margin beyond robot_radius

# Semantic map locations (check all copies)
SEMANTIC_MAP_PATHS = [
    SCRIPT_DIR / "campus_guide_bot/campus_nav_llm/semantic/semantic_map.json",
    SCRIPT_DIR / "campus_guide_bot/build/campus_nav_llm/semantic/semantic_map.json",
    SCRIPT_DIR / "install/campus_nav_llm/share/campus_nav_llm/semantic/semantic_map.json",
]


def world_to_pixel(wx, wy, resolution, origin, map_height):
    px = int((wx - origin[0]) / resolution)
    py = int(map_height - 1 - (wy - origin[1]) / resolution)
    return px, py


def min_obstacle_distance(arr, px, py, resolution, search_radius_px=20):
    h, w = arr.shape
    min_dist = float("inf")
    for dy in range(-search_radius_px, search_radius_px + 1):
        for dx in range(-search_radius_px, search_radius_px + 1):
            ny, nx = py + dy, px + dx
            if 0 <= ny < h and 0 <= nx < w and arr[ny, nx] == 0:
                d = ((dx * resolution) ** 2 + (dy * resolution) ** 2) ** 0.5
                if d < min_dist:
                    min_dist = d
    return min_dist


def find_nearest_safe(arr, px, py, resolution, min_clearance, search_radius_px=20):
    h, w = arr.shape
    best_dist = float("inf")
    best_px, best_py = px, py
    for dy in range(-search_radius_px, search_radius_px + 1):
        for dx in range(-search_radius_px, search_radius_px + 1):
            ny, nx = py + dy, px + dx
            if not (0 <= ny < h and 0 <= nx < w and arr[ny, nx] == 254):
                continue
            clearance = min_obstacle_distance(arr, nx, ny, resolution)
            if clearance >= min_clearance:
                pixel_dist = (dx ** 2 + dy ** 2) ** 0.5
                if pixel_dist < best_dist:
                    best_dist = pixel_dist
                    best_px, best_py = nx, ny
    if best_dist == float("inf"):
        return None, None
    wx = best_px * resolution + MAP_YAML_ORIGIN[0]
    wy = (h - 1 - best_py) * resolution + MAP_YAML_ORIGIN[1]
    return wx, wy


def main():
    fix_mode = "--fix" in sys.argv

    # Load map
    if not MAP_PGM.exists():
        print(f"ERROR: Map not found: {MAP_PGM}")
        sys.exit(1)
    arr = np.array(Image.open(MAP_PGM))
    h, w = arr.shape
    print(f"Map: {w}x{h} pixels, resolution={MAP_YAML_RESOLUTION}m/px")
    print(f"Robot radius: {ROBOT_RADIUS}m, safety margin: {SAFETY_MARGIN}m")
    print(f"Min clearance required: {ROBOT_RADIUS + SAFETY_MARGIN}m")
    print()

    # Load semantic map
    sem_path = None
    for p in SEMANTIC_MAP_PATHS:
        if p.exists():
            sem_path = p
            break
    if sem_path is None:
        print("ERROR: No semantic_map.json found")
        sys.exit(1)

    with open(sem_path) as f:
        sem = json.load(f)

    locations = sem.get("locations", {})
    min_clearance = ROBOT_RADIUS + SAFETY_MARGIN

    all_ok = True
    for name, loc in locations.items():
        wx, wy = loc["x"], loc["y"]
        px, py = world_to_pixel(wx, wy, MAP_YAML_RESOLUTION, MAP_YAML_ORIGIN, h)

        # Check bounds
        if not (0 <= px < w and 0 <= py < h):
            print(f"  FAIL  {name:20s} ({wx:7.2f}, {wy:7.2f}) — OUT OF MAP BOUNDS")
            all_ok = False
            continue

        pixel_val = arr[py, px]
        clearance = min_obstacle_distance(arr, px, py, MAP_YAML_RESOLUTION)

        if pixel_val == 0:
            status = "ON WALL"
            ok = False
        elif pixel_val == 205:
            status = "UNKNOWN AREA"
            ok = False
        elif clearance < min_clearance:
            status = f"TOO CLOSE ({clearance:.3f}m < {min_clearance:.3f}m)"
            ok = False
        else:
            status = f"OK (clearance={clearance:.3f}m)"
            ok = True

        icon = "  OK  " if ok else "  FAIL"
        print(f"{icon}  {name:20s} ({wx:7.2f}, {wy:7.2f})  {status}")

        if not ok:
            all_ok = False
            if fix_mode:
                sx, sy = find_nearest_safe(arr, px, py, MAP_YAML_RESOLUTION, min_clearance)
                if sx is not None:
                    sc = min_obstacle_distance(
                        arr,
                        *world_to_pixel(sx, sy, MAP_YAML_RESOLUTION, MAP_YAML_ORIGIN, h),
                        MAP_YAML_RESOLUTION,
                    )
                    print(f"         -> suggested fix: ({sx:.2f}, {sy:.2f}) clearance={sc:.3f}m")

    print()
    if all_ok:
        print("All coordinates are valid!")
    else:
        print("Some coordinates need fixing. Run with --fix to see suggestions.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

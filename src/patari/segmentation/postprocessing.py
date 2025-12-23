from __future__ import annotations

import numpy as np
from skimage.measure import find_contours

# TODO: this is copilot sample code. Refine / replace as needed.


# def class_mask(seg: np.ndarray, class_id: int) -> np.ndarray:
#     seg = np.asarray(seg)
#     return seg == int(class_id)


# def keep_largest_component(mask: np.ndarray) -> np.ndarray:
#     """Keep the largest connected component in a boolean mask."""

#     mask = np.asarray(mask, dtype=bool)
#     if mask.size == 0 or not mask.any():
#         return mask

#     # Simple BFS labeling without extra deps.
#     h, w = mask.shape
#     visited = np.zeros_like(mask, dtype=bool)

#     def neighbors(r: int, c: int):
#         if r > 0:
#             yield r - 1, c
#         if r + 1 < h:
#             yield r + 1, c
#         if c > 0:
#             yield r, c - 1
#         if c + 1 < w:
#             yield r, c + 1

#     best_coords: list[tuple[int, int]] = []

#     for r in range(h):
#         for c in range(w):
#             if not mask[r, c] or visited[r, c]:
#                 continue
#             stack = [(r, c)]
#             visited[r, c] = True
#             coords: list[tuple[int, int]] = [(r, c)]
#             while stack:
#                 rr, cc = stack.pop()
#                 for nr, nc in neighbors(rr, cc):
#                     if mask[nr, nc] and not visited[nr, nc]:
#                         visited[nr, nc] = True
#                         stack.append((nr, nc))
#                         coords.append((nr, nc))
#             if len(coords) > len(best_coords):
#                 best_coords = coords

#     out = np.zeros_like(mask, dtype=bool)
#     for r, c in best_coords:
#         out[r, c] = True
#     return out


# def mask_to_largest_contour_polygon_rc(mask: np.ndarray) -> np.ndarray | None:
#     """Return a single (N,2) contour polygon in (row,col) pixel coords.

#     Uses the longest contour returned by skimage.find_contours.
#     """

#     mask = np.asarray(mask, dtype=bool)
#     if mask.size == 0 or not mask.any():
#         return None

#     contours = find_contours(mask.astype(float), 0.5)
#     if not contours:
#         return None

#     largest = max(contours, key=lambda a: int(np.asarray(a).shape[0]))
#     poly = np.asarray(largest, dtype=float)
#     if poly.ndim != 2 or poly.shape[1] != 2 or poly.shape[0] < 3:
#         return None
#     return poly


# def polygon_rc_to_world_yx(
#     poly_rc: np.ndarray, *, sy: float, sx: float
# ) -> np.ndarray:
#     """Convert (row,col) pixel contour to (y,x) world coords (mm)."""

#     poly_rc = np.asarray(poly_rc, dtype=float)
#     yx_px = poly_rc[:, :2]  # (row,col)
#     return yx_px * np.array([float(sy), float(sx)], dtype=float)

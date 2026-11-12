// Limits come from the server (config.yaml is the single source of truth).
// The fallback values only apply if /api/limits cannot be reached; the server enforces the real
// limits regardless of what the browser allows.
import { api } from "./api.js";

export let limits = {
  project_name_max: 80, tag_max_length: 40, tags_per_image: 20, page_size: 60,
  class_name_max: 80, palette: ["#E69F00", "#56B4E9", "#009E73"], undo_limit: 500,
  save_debounce_ms: 400, min_box_px: 1, max_annotations: 2000, filmstrip_size: 15,
  min_polygon_area_px: 1, simplify_epsilon_px: 2, max_keypoints: 64, skeleton_name_max: 40,
};

try {
  limits = await api("/api/limits");
} catch {
  /* keep the fallback */
}

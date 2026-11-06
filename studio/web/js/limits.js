// Limits come from the server (config.yaml is the single source of truth).
// The fallback values only apply if /api/limits cannot be reached; the server enforces the real
// limits regardless of what the browser allows.
import { api } from "./api.js";

export let limits = { project_name_max: 80, tag_max_length: 40, tags_per_image: 20, page_size: 60 };

try {
  limits = await api("/api/limits");
} catch {
  /* keep the fallback */
}

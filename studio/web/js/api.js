// Thin client for the local API. Errors become Error objects with a readable message.

export class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.status = status;
    this.data = data; // the parsed error body, e.g. { detail, current_rev, in_use }
  }
}

function readableDetail(detail, status) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Please check the values you entered.";
  return status >= 500 ? "Something went wrong on the server." : "The request could not be completed.";
}

export async function api(path, { method = "GET", body, keepalive = false } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      keepalive, // lets the request finish while the page is being closed
    });
  } catch {
    throw new ApiError("Cannot reach the app. Is it still running?", 0);
  }
  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* non-JSON body */
  }
  if (!response.ok) throw new ApiError(readableDetail(data?.detail, response.status), response.status, data);
  return data;
}

// Watch an import job. Uses the WebSocket and falls back to polling if it cannot connect.
export function watchJob(jobId, onUpdate) {
  return new Promise((resolve) => {
    let finished = false;
    const finish = (job) => {
      if (finished) return;
      finished = true;
      resolve(job);
    };
    let polling = false;
    const poll = async () => {
      if (polling) return; // the socket can fire both error and close; poll only once
      polling = true;
      while (!finished) {
        try {
          const job = await api(`/api/jobs/${jobId}`);
          onUpdate(job);
          if (job.state === "done" || job.state === "failed") return finish(job);
        } catch (error) {
          return finish({ state: "failed", error: error.message });
        }
        await new Promise((r) => setTimeout(r, 500));
      }
    };
    try {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${scheme}://${location.host}/api/jobs/${jobId}/ws`);
      let last = null;
      socket.onmessage = (event) => {
        last = JSON.parse(event.data);
        onUpdate(last);
        if (last.state === "done" || last.state === "failed") finish(last);
      };
      socket.onerror = () => {
        if (!finished) poll();
      };
      socket.onclose = () => {
        if (!finished && !(last && (last.state === "done" || last.state === "failed"))) poll();
      };
    } catch {
      poll();
    }
  });
}

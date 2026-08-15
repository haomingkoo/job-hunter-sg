import { apiFetch } from "./api.js";


function decodeEvent(block) {
  const lines = block.split("\n");
  const eventId = lines.find((line) => line.startsWith("id: "))?.slice(4);
  const eventName = lines.find((line) => line.startsWith("event: "))?.slice(7);
  const data = lines
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6))
    .join("\n");
  if (!eventName || !data) return null;
  return { eventId, eventName, payload: JSON.parse(data) };
}


async function readStream(response, onActivity, accepted) {
  if (!response.body) throw new Error("The recruitment activity stream was unavailable.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let receipt = null;
  let streamError = null;

  function consume(block) {
    const decoded = decodeEvent(block);
    if (!decoded) return;
    if (decoded.eventName === "activity") {
      accepted.runId ||= decoded.payload.run_id;
      accepted.sequence = Math.max(
        accepted.sequence,
        Number(decoded.eventId || decoded.payload.sequence || 0),
      );
      onActivity(decoded.payload);
    }
    if (decoded.eventName === "receipt") receipt = decoded.payload;
    if (decoded.eventName === "error") streamError = decoded.payload;
  }

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      consume(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  if (buffer.trim()) consume(buffer.trim());
  if (streamError) {
    const error = new Error(streamError.message || "The recruitment team turn failed.");
    error.detail = streamError;
    throw error;
  }
  return receipt;
}


export async function streamRecruitmentCommand(path, body, onActivity) {
  const accepted = { runId: "", sequence: 0 };
  let receipt = null;
  try {
    const response = await apiFetch(path, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { Accept: "text/event-stream" },
    });
    receipt = await readStream(response, onActivity, accepted);
  } catch (error) {
    if (!accepted.runId || error.detail) throw error;
  }
  if (receipt) return receipt;
  if (!accepted.runId) {
    throw new Error("The recruitment stream ended before the run was accepted. Submit the turn again.");
  }

  const replay = await apiFetch(
    `/api/recruitment-team/runs/${encodeURIComponent(accepted.runId)}/stream?after_sequence=${accepted.sequence}`,
    { headers: { Accept: "text/event-stream" } },
  );
  receipt = await readStream(replay, onActivity, accepted);
  if (!receipt) throw new Error("The accepted recruitment run could not be reattached.");
  return receipt;
}

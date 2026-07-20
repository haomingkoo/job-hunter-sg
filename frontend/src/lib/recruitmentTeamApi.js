import { apiFetch } from "./api.js";


function decodeEvent(block) {
  const lines = block.split("\n");
  const eventName = lines.find((line) => line.startsWith("event: "))?.slice(7);
  const data = lines
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6))
    .join("\n");
  if (!eventName || !data) return null;
  return { eventName, payload: JSON.parse(data) };
}


export async function streamRecruitmentCommand(path, body, onActivity) {
  const response = await apiFetch(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { Accept: "text/event-stream" },
  });
  if (!response.body) throw new Error("The recruitment activity stream was unavailable.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let receipt = null;

  function consume(block) {
    const decoded = decodeEvent(block);
    if (!decoded) return;
    if (decoded.eventName === "activity") onActivity(decoded.payload);
    if (decoded.eventName === "receipt") receipt = decoded.payload;
    if (decoded.eventName === "error") {
      throw new Error(decoded.payload.message || "The recruitment team turn failed.");
    }
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
  if (!receipt) throw new Error("The recruitment team stream ended without a receipt.");
  return receipt;
}

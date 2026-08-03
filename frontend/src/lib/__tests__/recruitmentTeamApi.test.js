import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api.js";
import { streamRecruitmentCommand } from "../recruitmentTeamApi.js";

vi.mock("../api.js", () => ({ apiFetch: vi.fn() }));


function streamedResponse(chunks) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    body: {
      getReader: () => ({
        read: async () => {
          if (index === chunks.length) return { done: true, value: undefined };
          const value = encoder.encode(chunks[index]);
          index += 1;
          return { done: false, value };
        },
      }),
    },
  };
}


describe("streamRecruitmentCommand", () => {
  beforeEach(() => vi.clearAllMocks());

  it("emits chunk-split activity and returns the final receipt", async () => {
    apiFetch.mockResolvedValue(streamedResponse([
      "event: activity\ndata: {\"sequence\":1,\"status\":\"run",
      "ning\"}\n\nevent: receipt\ndata: {\"thread_id\":\"thread-1\"}\n\n",
    ]));
    const activities = [];

    const receipt = await streamRecruitmentCommand(
      "/api/recruitment-team/threads/stream",
      { message: "Find roles." },
      (event) => activities.push(event),
    );

    expect(activities).toEqual([{ sequence: 1, status: "running" }]);
    expect(receipt).toEqual({ thread_id: "thread-1" });
  });

  it("ignores heartbeat metadata without adding fake activity", async () => {
    apiFetch.mockResolvedValue(streamedResponse([
      'event: heartbeat\ndata: {"status":"running"}\n\n',
      'event: receipt\ndata: {"thread_id":"thread-1"}\n\n',
    ]));
    const onActivity = vi.fn();

    const receipt = await streamRecruitmentCommand(
      "/api/recruitment-team/threads/stream",
      { message: "Find roles." },
      onActivity,
    );

    expect(onActivity).not.toHaveBeenCalled();
    expect(receipt).toEqual({ thread_id: "thread-1" });
  });
});

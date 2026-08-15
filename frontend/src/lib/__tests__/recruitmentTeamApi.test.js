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


function interruptedResponse(chunks) {
  const response = streamedResponse(chunks);
  const reader = response.body.getReader();
  response.body.getReader = () => ({
    read: async () => {
      const result = await reader.read();
      if (result.done) throw new TypeError("network disconnected");
      return result;
    },
  });
  return response;
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

  it("reattaches an accepted run from its last durable sequence without reposting", async () => {
    apiFetch
      .mockResolvedValueOnce(interruptedResponse([
        'event: activity\ndata: {"sequence":1,"run_id":"run-1","status":"running"}\nid: 1\n\n',
      ]))
      .mockResolvedValueOnce(streamedResponse([
        'event: activity\ndata: {"sequence":2,"run_id":"run-1","status":"completed"}\nid: 2\n\n',
        'event: receipt\ndata: {"run_id":"run-1","thread_id":"thread-1"}\n\n',
      ]));
    const onActivity = vi.fn();

    const receipt = await streamRecruitmentCommand(
      "/api/recruitment-team/threads/thread-1/messages/stream",
      { message: "Continue." },
      onActivity,
    );

    expect(receipt).toEqual({ run_id: "run-1", thread_id: "thread-1" });
    expect(onActivity.mock.calls.map(([event]) => event.sequence)).toEqual([1, 2]);
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(apiFetch.mock.calls[0][1].method).toBe("POST");
    expect(apiFetch.mock.calls[1][0]).toBe(
      "/api/recruitment-team/runs/run-1/stream?after_sequence=1",
    );
    expect(apiFetch.mock.calls[1][1].method).toBeUndefined();
  });

  it("does not resubmit when the stream ends before a run is accepted", async () => {
    apiFetch.mockResolvedValue(streamedResponse([]));

    await expect(streamRecruitmentCommand(
      "/api/recruitment-team/threads/stream",
      { message: "Find roles." },
      vi.fn(),
    )).rejects.toThrow("before the run was accepted");
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });
});

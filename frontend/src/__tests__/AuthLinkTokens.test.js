import { afterEach, describe, expect, it } from "vitest";

import { readAuthLinkTokens, removeAuthLinkTokensFromUrl } from "../App.jsx";

describe("email auth link tokens", () => {
  afterEach(() => window.history.replaceState({}, "", "/"));

  it("reads fragment tokens before legacy query tokens", () => {
    const tokens = readAuthLinkTokens(
      "https://job.example/?reset_token=legacy-reset&verify_token=legacy-verify#reset_token=fragment-reset&verify_token=fragment-verify",
    );

    expect(tokens).toEqual({
      reset_token: "fragment-reset",
      verify_token: "fragment-verify",
    });
    expect(readAuthLinkTokens("https://job.example/?reset_token=legacy-reset&verify_token=legacy-verify"))
      .toEqual({ reset_token: "legacy-reset", verify_token: "legacy-verify" });
  });

  it("removes token secrets while preserving unrelated URL state", () => {
    window.history.replaceState(
      {},
      "",
      "/?source=mcf&verify_token=legacy#reset_token=fragment&tab=account",
    );

    removeAuthLinkTokensFromUrl();

    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("?source=mcf");
    expect(window.location.hash).toBe("#tab=account");
  });
});

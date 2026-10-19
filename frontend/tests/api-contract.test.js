import { afterEach, describe, expect, it, vi } from "vitest";
import { createLiveSession } from "../src/api.js";

describe("live API contract", () => {
  afterEach(() => vi.restoreAllMocks());

  it("posts the documented camelCase session configuration and returns the backend receipt", async () => {
    const receipt = { sessionId: "session-contract", state: "created", metrics: { received: 0 } };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => receipt,
    });

    const result = await createLiveSession({
      scenario: "stable-baseline",
      durationSec: 12,
      sampleRateHz: 2,
      speed: 1,
      seed: 7,
      faults: [],
      noWait: false,
    });

    expect(result).toEqual(receipt);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/live/sessions",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario: "stable-baseline",
          durationSec: 12,
          sampleRateHz: 2,
          speed: 1,
          seed: 7,
          faults: [],
          noWait: false,
        }),
      }),
    );
  });
});

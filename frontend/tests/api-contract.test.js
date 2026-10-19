import { afterEach, describe, expect, it, vi } from "vitest";
import { createLiveSession, getLiveReplay, listLiveSessions } from "../src/api.js";

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

  it("reads the bounded session catalog for a future history screen", async () => {
    const catalog = { sessions: [], limit: 25 };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => catalog,
    });

    await expect(listLiveSessions(25)).resolves.toEqual(catalog);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/live/sessions?limit=25", expect.anything());
  });

  it("reads persisted samples through the replay contract", async () => {
    const replay = { sessionId: "session/review", sourceType: "replay", sampleCount: 1, samples: [] };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => replay,
    });

    await expect(getLiveReplay("session/review")).resolves.toEqual(replay);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/live/sessions/session%2Freview/replay", expect.anything());
  });
});

import { describe, expect, it } from "vitest";
import {
  channelQuality,
  channelTrend,
  channelTrust,
  channelValue,
  initialLiveState,
  reduceLiveEvent,
  statusCopy,
} from "../src/sessionModel.js";

describe("live session event contract", () => {
  it("keeps a deterministic user-flow view of status, samples, quality, and failures", () => {
    const created = reduceLiveEvent(initialLiveState, {
      type: "status",
      payload: { state: "streaming", metrics: { received: 0, missing: 0 } },
    });
    expect(statusCopy(created).label).toBe("Stream healthy");

    const sample = {
      sampleId: "sample-1",
      relativeTimeSec: 0,
      values: { spo2: 97.2, "heart-rate": 74, respiration: 16 },
      qualityFlags: [],
    };
    const withSample = reduceLiveEvent(created, {
      type: "sample",
      payload: { sample },
    });
    expect(channelValue(withSample.latestSample, "spo2")).toBe("97.2");
    expect(channelQuality(withSample.latestSample, null, "spo2")).toBe("No quality flags");

    const missing = reduceLiveEvent(withSample, {
      type: "sample",
      payload: {
        sample: {
          ...sample,
          sampleId: "sample-2",
          values: { ...sample.values, spo2: null },
          qualityFlags: ["missing"],
        },
      },
    });
    expect(statusCopy(missing).label).toBe("Some readings are missing");
    expect(channelQuality(missing.latestSample, null, "spo2")).toBe("Missing reading");

    const reviewed = reduceLiveEvent(missing, {
      type: "failure",
      payload: {
        failure: {
          failureId: "failure-1",
          type: "packet_loss",
          status: "open",
          affectedChannels: ["spo2"],
        },
      },
    });
    expect(reviewed.failures).toHaveLength(1);
    expect(statusCopy(reviewed).detail).toContain("cautious");
  });

  it("does not invent trend or trust values when the live envelope omits them", () => {
    const sample = { values: { spo2: 96 }, qualityFlags: [] };
    const state = reduceLiveEvent(initialLiveState, { type: "sample", payload: { sample } });
    expect(state.latestSample).toEqual(sample);
    expect(channelTrend(state.latestSample, "spo2")).toBe("Not supplied by live stream");
    expect(channelTrust(state.latestSample, "spo2")).toBe("Not supplied");
    expect(statusCopy(state).label).toBe("Ready to begin");
  });
});

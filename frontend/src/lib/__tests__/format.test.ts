import { describe, expect, it } from "vitest";
import { fmtDuration, runDurationSeconds } from "@/lib/format";

describe("saved run duration", () => {
  it("uses recorded UTC timestamps, including older SQLite timestamps without offsets", () => {
    expect(runDurationSeconds({ started_at: "2026-01-01T00:00:00", completed_at: "2026-01-01T00:25:46Z" })).toBe(1546);
    expect(runDurationSeconds({ started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:25:46" })).toBe(1546);
    expect(runDurationSeconds({ started_at: "2026-01-01T00:00:00Z", completed_at: "2025-12-31T19:25:46-05:00" })).toBe(1546);
  });

  it("shows unknown for missing, invalid or reversed timing instead of inventing a duration", () => {
    for (const run of [
      {}, { started_at: "2026-01-01T00:00:00Z" }, { completed_at: "2026-01-01T00:00:00Z" },
      { started_at: "invalid", completed_at: "2026-01-01T00:00:00Z" },
      { started_at: "2026-01-02T00:00:00Z", completed_at: "2026-01-01T00:00:00Z" },
    ]) expect(fmtDuration(runDurationSeconds(run))).toBe("—");
  });

  it("includes hours and seconds in long runs without resetting at one day", () => {
    expect(fmtDuration(1546)).toBe("25m 46s");
    expect(fmtDuration(3723)).toBe("1h 2m 3s");
    expect(fmtDuration(90000)).toBe("25h 0m 0s");
    expect(fmtDuration(0)).toBe("0s");
  });
});

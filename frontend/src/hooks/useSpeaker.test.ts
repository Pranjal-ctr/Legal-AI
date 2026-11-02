import { describe, expect, it } from "vitest";

import { splitForSpeech } from "./useSpeaker";

describe("splitForSpeech", () => {
  it("groups sentences into chunks of at most ~300 characters", () => {
    const long = "A".repeat(200);
    expect(splitForSpeech(`One. Two? Three!`)).toEqual(["One. Two? Three!"]);
    expect(splitForSpeech(`${long}. ${long}.`)).toEqual([`${long}.`, `${long}.`]);
    expect(splitForSpeech("पहला वाक्य। दूसरा।\n\nतीसरा")).toEqual(["पहला वाक्य। दूसरा। तीसरा"]);
    expect(splitForSpeech("   ")).toEqual([]);
  });
});

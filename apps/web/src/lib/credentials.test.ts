import { describe, expect, it } from "vitest";

import type { CredentialsOut } from "./api/client";
import { describeCredentials } from "./credentials";

const base: CredentialsOut = {
  state: "none",
  trust_list: "c2pa-trust-list@64b3f9c",
  validation_state: null,
  failures: [],
  signer_issuer: null,
  signer_common_name: null,
  signed_at: null,
  claim_generator: null,
  title: null,
  actions: [],
  error: null,
};

describe("describeCredentials", () => {
  it("never reads absence as evidence", () => {
    expect(describeCredentials(base).meaning).toContain("absence proves nothing");
  });

  it("separates an invalid manifest from a merely untrusted one", () => {
    const untrusted = describeCredentials({
      ...base,
      state: "present_untrusted",
      validation_state: "Valid",
      failures: ["signingCredential.untrusted"],
    });
    const invalid = describeCredentials({
      ...base,
      state: "present_untrusted",
      validation_state: "Invalid",
      failures: ["assertion.dataHash.mismatch"],
    });
    expect(untrusted.label).toBe("Signed, signer not trusted");
    expect(untrusted.tampered).toBe(false);
    expect(invalid.label).toBe("Credentials present but invalid");
    expect(invalid.tampered).toBe(true);
  });

  it("does not let a trusted signature claim truth", () => {
    const verdict = describeCredentials({ ...base, state: "valid_trusted", validation_state: "Trusted" });
    expect(verdict.meaning).toContain("not that the picture is truthful");
  });

  it("reports unreadable credentials with the reason", () => {
    const verdict = describeCredentials({ ...base, state: "present_untrusted", error: "manifest unreadable: bad box" });
    expect(verdict.label).toBe("Credentials present but unreadable");
    expect(verdict.meaning).toContain("bad box");
  });
});

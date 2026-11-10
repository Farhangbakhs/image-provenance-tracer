import type { CredentialsOut } from "./api/client";

export interface CredentialsVerdict {
  /** Short label for the state. */
  label: string;
  /** What the analyst may and may not conclude from it. */
  meaning: string;
  /** True when the file was changed after it was signed. */
  tampered: boolean;
}

/**
 * Plain-language reading of a Content Credentials result. Each sentence states the limit of
 * what C2PA shows: who signed, and whether the bytes changed since. Never that the picture is true.
 */
export function describeCredentials(credentials: CredentialsOut): CredentialsVerdict {
  if (credentials.state === "none") {
    return {
      label: "No Content Credentials",
      meaning:
        credentials.error ??
        "This file carries no C2PA manifest. Most images online have none, and platforms often strip them, so absence proves nothing.",
      tampered: false,
    };
  }
  if (credentials.state === "valid_trusted") {
    return {
      label: "Signed by a trusted signer, intact",
      meaning:
        "The signature validates and chains to the C2PA trust list. It shows who signed the file and when, not that the picture is truthful.",
      tampered: false,
    };
  }
  if (credentials.validation_state === "Invalid") {
    return {
      label: "Credentials present but invalid",
      meaning:
        "The manifest does not match the file: it was changed after signing, or the manifest is damaged. Treat any claim it makes as unverified.",
      tampered: true,
    };
  }
  if (credentials.error) {
    return {
      label: "Credentials present but unreadable",
      meaning: `C2PA data was found but could not be read (${credentials.error}).`,
      tampered: false,
    };
  }
  return {
    label: "Signed, signer not trusted",
    meaning:
      "The signature is intact, but the signer is not on the C2PA trust list, so nobody vouches for who signed it.",
    tampered: false,
  };
}

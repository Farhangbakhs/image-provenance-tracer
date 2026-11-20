/** A domain as people say it: without the leading "www.". */
export function bareDomain(domain: string): string {
  return domain.replace(/^www\./i, "");
}

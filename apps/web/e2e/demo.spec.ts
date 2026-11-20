import { expect, test, type Page } from "@playwright/test";

const API = process.env.ORIGIN_API_URL ?? "http://localhost:8000";
const DISCLAIMER = "Earliest found in indexed sources. Earlier copies may exist.";
const FLOOD = "DEMO: Flood photo recaptioned as a hurricane";
const TELEGRAM = "DEMO: Harbour smoke posted on Telegram before the web";

/** Next keeps the previous route mounted but hidden after a client navigation; match only what is shown. */
function shown(page: Page, text: string | RegExp) {
  return page.getByText(text).filter({ visible: true });
}

async function openWorkspace(page: Page, title: string) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.locator('a[href^="/assets/"]').first().click();
  await page.getByRole("link", { name: /Open investigation/ }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
}

test("home shows the demo cases and every service is ready", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(shown(page, DISCLAIMER).first()).toBeVisible();
  for (const title of [FLOOD, "DEMO: Cropped and captioned repost", "DEMO: Signed photo, stripped copies", TELEGRAM]) {
    await expect(page.getByRole("link", { name: new RegExp(title) })).toBeVisible();
  }
  const status = page.getByRole("region", { name: "System" });
  await expect(status.getByText("ready", { exact: true })).toBeVisible();
  for (const name of ["Database", "Job queue", "Object storage"]) {
    await expect(status.getByText(name)).toBeVisible();
  }
  await expect(status.getByText("down", { exact: true })).toHaveCount(0);
});

test("the miscaptioned case answers first, then shows its stories in order", async ({ page }) => {
  await openWorkspace(page, FLOOD);
  const summary = page.getByRole("region", { name: "Summary" });
  await expect(summary).toContainText("First found 30 Oct 2024 on valencia-news.example as Floods in Valencia");
  await expect(summary).toContainText("Since reused in 1 other story, which contradicts it.");
  await expect(shown(page, DISCLAIMER).first()).toBeVisible();

  // The earliest copy is already selected: its evidence is open with no click.
  const drawer = page.getByRole("complementary", { name: "Evidence" });
  await expect(drawer.getByText(/valencia-news\.example/).first()).toBeVisible();

  // Stories are rows, the original first, each with its status in words.
  const rows = page.getByRole("button", { name: /(Original story|Contradicts original) · \d+ cop/ });
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Original story");
  await expect(rows.nth(1)).toContainText("Contradicts original");

  // Clicking a dot selects its copy, and its evidence opens.
  await page.getByRole("button", { name: /viral-wire\.example/ }).click();
  await expect(drawer.getByText(/viral-wire\.example/).first()).toBeVisible();

  // Clicking a story lists its copies in the side panel.
  await rows.nth(1).click();
  await expect(page.getByRole("complementary", { name: "Story" })).toContainText("Hurricane Milton");

  // How it looks: the variants, with the mirror edit.
  await page.getByRole("radio", { name: "How it looks" }).click();
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.getByRole("list", { name: "Graph in words" })).toContainText("mirrored");
  await page.keyboard.press("g");
  await expect(page.getByRole("tab", { name: "list" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("cell", { name: /viral-wire\.example/ }).first()).toBeVisible();
});

test("the Telegram case is earliest on Telegram and shows the forward", async ({ page }) => {
  await openWorkspace(page, TELEGRAM);
  const summary = page.getByRole("region", { name: "Summary" });
  await expect(summary).toContainText("11 May 2024");
  await expect(summary).toContainText("t.me");

  // The earliest sighting is the channel post the watchlist post was forwarded from, and its
  // evidence is already open.
  const drawer = page.getByRole("complementary", { name: "Evidence" });
  await expect(drawer.getByText(/origin_demo_citydesk\/52/).first()).toBeVisible();
  await expect(drawer.getByText(/platform/).first()).toBeVisible();

  // The forward is an edge between copies, drawn in the lineage.
  await page.getByRole("radio", { name: "How it looks" }).click();
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.getByRole("list", { name: "Graph in words" })).toContainText("forwarded");
});

test("the brief cites the branch and prints to PDF", async ({ page }) => {
  await openWorkspace(page, FLOOD);
  await page.getByRole("link", { name: "Brief (PDF)" }).click();
  await expect(shown(page, /Earliest found:/)).toBeVisible();
  await expect(shown(page, DISCLAIMER).first()).toBeVisible();
  await expect(shown(page, /^Branch: /)).toContainText(/Milton|Florida|Tampa/);
  await expect(shown(page, /Diverges at S\d/)).toBeVisible();

  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("button", { name: "Print or save as PDF" })).toBeHidden();
  const pdf = await page.pdf({ format: "A4", printBackground: true });
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  expect(pdf.byteLength).toBeGreaterThan(10_000);
});

test("the evidence pack lists every artefact with its hash", async ({ page, request }) => {
  await openWorkspace(page, FLOOD);
  const runId = page.url().split("/").pop() as string;
  const response = await request.get(`${API}/runs/${runId}/evidence-pack?download=true`);
  expect(response.ok()).toBe(true);
  expect(response.headers()["content-disposition"]).toContain(`origin-run-${runId}.json`);
  const pack = await response.json();
  expect(pack.disclaimer).toBe(DISCLAIMER);
  expect(pack.sightings.sightings).toHaveLength(3);
  expect(pack.artefacts.length).toBeGreaterThanOrEqual(4);
  for (const artefact of pack.artefacts) {
    expect(artefact.sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(artefact.fetched_at).toBeTruthy();
  }
});

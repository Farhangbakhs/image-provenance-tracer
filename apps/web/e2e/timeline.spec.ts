import { expect, test, type Page } from "@playwright/test";

/**
 * The zoomable timeline, on a live trace (the Khan Yunis image): its copies sit in Nov 2019 to
 * Jan 2020, a few more were proven only by a 2026 fetch, and some bundle: three copies share one
 * instant on 15 Nov 2019 and six more sit on 7 and 8 Jan 2020.
 * Set ORIGIN_E2E_ZOOM_RUN to the run id of such a trace; the tests skip if the run is absent.
 */
const API = process.env.ORIGIN_API_URL ?? "http://localhost:8000";
const RUN = process.env.ORIGIN_E2E_ZOOM_RUN ?? "6fa0e492-c34b-48ea-9b95-6814d1ed6145";

test.beforeEach(async ({ request }) => {
  const response = await request.get(`${API}/runs/${RUN}`);
  test.skip(!response.ok(), `run ${RUN} is not in this database`);
});

async function open(page: Page) {
  await page.goto(`/runs/${RUN}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("overview-range")).toBeVisible();
}

const range = (page: Page) => page.getByTestId("overview-range");
const uncaptioned = (page: Page) => page.getByRole("group", { name: "Copies with no readable caption" });
const marks = (page: Page) => uncaptioned(page).locator("[data-mark]");
const six = (page: Page) => uncaptioned(page).getByRole("button", { name: "6 copies close together" });
const three = (page: Page) => uncaptioned(page).getByRole("button", { name: "3 copies close together" });

async function ctrlScroll(page: Page, x: number, y: number, steps: number, deltaY: number) {
  await page.mouse.move(x, y);
  await page.keyboard.down("Control");
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, deltaY);
    await page.waitForTimeout(30);
  }
  await page.keyboard.up("Control");
}

/** Gaps between neighbouring marks in every row, in px. */
function gaps(page: Page) {
  return page.evaluate(() => {
    const rows = new Map<string, number[]>();
    document.querySelectorAll<SVGGElement>("[data-mark]").forEach((el) => {
      const row = el.dataset.row as string;
      rows.set(row, [...(rows.get(row) ?? []), Number(el.dataset.x)]);
    });
    return [...rows.values()].flatMap((xs) => xs.sort((a, b) => a - b).slice(1).map((x, i) => x - xs[i]));
  });
}

test("the default view holds the dense period with the earliest copy, not the whole range", async ({ page }) => {
  await open(page);
  await expect(range(page)).toHaveText("Nov 2019 – Jan 2020");
  await expect(page.getByRole("button", { name: "Reset view" })).toBeDisabled(); // already at the default
});

test("plain scrolling scrolls the page and does not zoom, and says how to zoom once", async ({ page }) => {
  await open(page);
  const before = await range(page).innerText();
  const box = (await page.getByTestId("timeline").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + 60);
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await page.mouse.wheel(0, 300);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(scrollBefore);
  expect(await range(page).innerText()).toBe(before);
  await expect(page.getByText("Ctrl + scroll to zoom")).toBeVisible();
  await expect(page.getByText("Ctrl + scroll to zoom")).toBeHidden({ timeout: 4000 }); // fades after 2 s

  // Never again in this session.
  await page.mouse.wheel(0, 300);
  await page.waitForTimeout(300);
  await expect(page.getByText("Ctrl + scroll to zoom")).toBeHidden();
});

test("Ctrl + scroll into 7 and 8 Jan opens the bundle of 6 into separate copies, and Reset view comes back", async ({ page }) => {
  await open(page);
  const initial = await range(page).innerText();
  await expect(six(page)).toBeVisible();
  const box = (await six(page).boundingBox())!;
  // Five steps in: a few days wide, so 7 Jan and 8 Jan are both still in view, a day apart.
  await ctrlScroll(page, box.x + box.width / 2, box.y + box.height / 2, 5, -240);

  await expect(six(page)).toHaveCount(0); // the 6 has split: one copy on 7 Jan, the rest on 8 Jan
  expect(await marks(page).count()).toBeGreaterThanOrEqual(2);
  expect(await range(page).innerText()).not.toBe(initial);
  // However far in, no two marks in any row are closer than 16 px.
  for (const gap of await gaps(page)) expect(gap).toBeGreaterThanOrEqual(16);

  await page.getByRole("button", { name: "Reset view" }).click();
  await expect(range(page)).toHaveText(initial, { timeout: 2000 });
  await expect(page.getByRole("button", { name: "Reset view" })).toBeDisabled();
});

test("clicking a bundle that can be told apart zooms to fit its copies", async ({ page }) => {
  await open(page);
  const initial = await range(page).innerText();
  await six(page).click();
  await expect(range(page)).not.toHaveText(initial, { timeout: 2000 });
  await expect(page.getByRole("button", { name: "Reset view" })).toBeEnabled();
  await expect(six(page)).toHaveCount(0);
});

test("copies on one instant cannot be told apart, so the side panel lists them", async ({ page }) => {
  await open(page);
  const initial = await range(page).innerText();
  await three(page).click();
  const panel = page.getByRole("complementary", { name: "Copies close together" });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("button")).toHaveCount(4); // the close button and the three copies
  await expect(panel).toContainText("bbc.co.uk"); // domains without "www."
  expect(await range(page).innerText()).toBe(initial); // and the view did not move
});

test("the keyboard zooms, pans and resets", async ({ page }) => {
  await open(page);
  const initial = await range(page).innerText();
  await page.keyboard.press("+");
  await expect(range(page)).not.toHaveText(initial, { timeout: 2000 });
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("0");
  await expect(range(page)).toHaveText(initial, { timeout: 2000 });
});

test("the overview and the graph stay in step", async ({ page }) => {
  await open(page);
  const win = page.getByTestId("overview-window");
  const before = (await win.boundingBox())!;
  // Dragging the window's right edge inwards zooms the graph.
  await page.mouse.move(before.x + before.width, before.y + before.height / 2);
  await page.mouse.down();
  await page.mouse.move(before.x + before.width - before.width / 2, before.y + before.height / 2, { steps: 6 });
  await page.mouse.up();
  const after = (await win.boundingBox())!;
  expect(after.width).toBeLessThan(before.width);
  await expect(range(page)).not.toHaveText("Nov 2019 – Jan 2020");
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("a bundle click lands at once, with no animation", async ({ page }) => {
    await open(page);
    const initial = await range(page).innerText();
    await six(page).click();
    await page.waitForTimeout(40); // far less than the 250 ms of the animation
    const soon = await range(page).innerText();
    await page.waitForTimeout(500);
    expect(soon).not.toBe(initial);
    expect(await range(page).innerText()).toBe(soon);
  });
});

import puppeteer from 'puppeteer-core';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--enable-unsafe-swiftshader', '--no-sandbox', '--window-size=1000,800'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1000, height: 800 });

const errors = [];
const external = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));
page.on('request', (r) => {
  const u = r.url();
  if (!/^(http:\/\/localhost|data:|blob:)/.test(u)) external.push(u);
});

await page.goto('http://localhost:8080/play', { waitUntil: 'networkidle2', timeout: 30000 });
await page.click('#guessButton');                       // switch to map view
await new Promise((r) => setTimeout(r, 9000));          // let vector tiles load + render

// Simulate placing a guess: click the map, then lock it in.
await page.mouse.click(500, 400);
await new Promise((r) => setTimeout(r, 800));
const guessMarkers = await page.$$eval('img.leaflet-marker-icon', (els) => els.length);
const lockEnabled = await page.$eval('#lockButton', (b) => !b.disabled);
await page.click('#lockButton');
await new Promise((r) => setTimeout(r, 1500));
const markersAfterLock = await page.$$eval('img.leaflet-marker-icon', (els) => els.length);
const resultText = await page.$eval('#result', (el) => el.textContent.replace(/\s+/g, ' ').trim());
await page.screenshot({ path: '/tmp/play_map.png' });

const skip = /ReadPixels|GL Driver|404|photos/;
console.log('EXTERNAL_REQUESTS:', external.length ? '\n  ' + external.join('\n  ') : 'none');
console.log('guess marker after click:', guessMarkers, '| lock button enabled:', lockEnabled);
console.log('markers after lock (guess+target):', markersAfterLock);
console.log('result panel:', resultText || '(empty)');
console.log('CONSOLE_ERRORS (non-photo):', errors.filter((e) => !skip.test(e)).join(' || ') || 'none');
await browser.close();

// Build-time only: render the vendored MIT robot-heads canvas into offline frames.
// Requires Node >= 24 and Playwright; the desktop pet needs neither at runtime.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { stripTypeScriptTypes } = require('node:module');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'assets', 'robot-heads');
const source = path.join(assets, 'source', 'src');
const fps = 20, count = 160, size = 128, dpr = 1.5;
const states = ['idle', 'listening', 'thinking', 'speaking', 'sleeping', 'error', 'happy', 'working', 'searching'];
const entry = `
import { getShape } from '/tv/geometry.js';
import { RobotSim } from '/tv/sim.js';
import { RobotRenderer, frameFor } from '/tv/render.js';
import { linear } from '/tv/light.js';
const shape = getShape('circle');
const frame = frameFor(shape, true, ${size});
const canvas = document.querySelector('canvas');
canvas.width = Math.round((frame.box + 2 * frame.padSide) * ${dpr});
canvas.height = Math.round((frame.box + frame.padTop + frame.padBottom) * ${dpr});
const palette = {
 shell: {albedo: linear([37, 151, 145]), f0: .05, metal: .15, spec: .55, shininess: 70, rim: .9},
 trim: {albedo: linear([167, 212, 211]), f0: .2, metal: .65, spec: .8, shininess: 45, rim: .7},
 led: [219, 255, 244]
};
const renderer = new RobotRenderer();
let sim, state;
window.begin = s => {
 state = s; sim = new RobotSim(.37, s);
 for (let i = 0; i < 120; i++) sim.update(1/120);
 return {width: canvas.width, height: canvas.height, frame};
};
window.next = () => {
 renderer.draw(canvas.getContext('2d'), frame, ${dpr}, sim.pose, sim, state, shape, palette,
   {floorShadow:true, antenna:true});
 const png = canvas.toDataURL('image/png').split(',')[1];
 sim.update(1/${fps}); return png;
};
window.ready = true;
`;
const modules = new Map();
for (const file of ['geometry','sim','render','faces','light']) {
 const ts = fs.readFileSync(path.join(source, 'tv', file + '.ts'), 'utf8');
 modules.set('/tv/' + file + '.js', stripTypeScriptTypes(ts, {mode:'transform'})
   .replace(/from '(\.\.?\/[^']+)'/g, "from '$1.js'"));
}
modules.set('/entry.js', entry);
const server = http.createServer((req, res) => {
 if (req.url === '/') {
   res.setHeader('Content-Type','text/html');
   res.end('<!doctype html><canvas></canvas><script type="module" src="/entry.js"></script>');
 } else if (modules.has(req.url)) {
   res.setHeader('Content-Type','text/javascript'); res.end(modules.get(req.url));
 } else { res.writeHead(404); res.end(); }
});
(async () => {
 await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
 let browser;
 try {
   browser = await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless:true});
   const page = await browser.newPage();
   const origin = `http://127.0.0.1:${server.address().port}`;
   await page.route('**/*', route => route.request().url().startsWith(origin + '/') ? route.continue() : route.abort());
   page.on('pageerror', err => { throw err; });
   await page.goto(origin); await page.waitForFunction(() => window.ready);
   let dimensions;
   for (const state of states) {
     dimensions = await page.evaluate(s => window.begin(s), state);
     const dir = path.join(assets, 'frames', state); fs.mkdirSync(dir,{recursive:true});
     for (let i = 0; i < count; i++) {
       const data = await page.evaluate(() => window.next());
       fs.writeFileSync(path.join(dir, String(i).padStart(3,'0') + '.png'), Buffer.from(data, 'base64'));
     }
     console.log(state + ': ' + count + ' frames');
   }
   fs.writeFileSync(path.join(assets,'manifest.json'), JSON.stringify({
     format:1, source:'https://github.com/fayazara/robot-heads',
     revision:'58ebf6439a8125a769f63b22ffd35bc18834b1b5', license:'MIT',
     shape:'circle', color:'#259791', fps, count, size, dpr, states, ...dimensions
   }, null, 2) + '\n');
 } finally { if(browser) await browser.close(); server.close(); }
})().catch(err => { console.error(err); process.exitCode=1; });

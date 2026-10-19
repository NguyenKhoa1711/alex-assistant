// Build a self-contained local canvas from the vendored MIT robot-heads sources.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {stripTypeScriptTypes} = require('node:module');
const root = path.resolve(__dirname, '..');
const source = process.argv[2] || path.join(root, 'assets/robot-heads/source/src');
const parts = ['geometry','light','faces','sim','render'].map(name => {
  let ts = fs.readFileSync(path.join(source,'tv',name+'.ts'),'utf8');
  // At a 110px head these extra quads are smaller than a pixel. Preserve the
  // original geometry/lighting but lower mesh subdivisions for a desktop pet.
  if (name === 'geometry') {
    for (const [from,to] of [['bevelSteps = 10','bevelSteps = 4'],
                            ['(sweep / (Math.PI / 2)) * 14','(sweep / (Math.PI / 2)) * 8'],
                            ['segments = 36','segments = 16']]) {
      if (!ts.includes(from)) throw Error('Upstream geometry changed: '+from);
      ts = ts.replace(from,to);
    }
  }
  let js = stripTypeScriptTypes(ts, {mode:'transform'});
  const exports = [...js.matchAll(/export (?:const|let|function|class) (\w+)/g)].map(match => match[1]);
  js = js.replace(/import\s*\{([^}]+)\}\s*from\s*'\.\/([^']+)'\s*;/g,
    (_, names, from) => `const {${names}} = ${from};`)
    .replace(/export (?=(?:const|let|function|class)\b)/g, '');
  if (/\bimport\s|\bexport\s/.test(js)) throw Error('Unconverted module in '+name);
  return `const ${name} = (() => {\n${js}\nreturn {${exports.join(',')}};\n})();`;
});
const entry = fs.readFileSync(path.join(__dirname,'robot_live_entry.js'),'utf8');
const script = `/* robot-heads (c) 2026 Fayaz Ahmed, MIT; see adjacent LICENSE. */\n(() => {\n'use strict';\n${parts.join('\n')}\n${entry}\n})();`;
const style = 'html,body{margin:0;padding:0;background:transparent;overflow:hidden;width:100%;height:100%;user-select:none}canvas{display:block;pointer-events:none}';
const hash = value => crypto.createHash('sha256').update(value).digest('base64');
const csp = `default-src 'none'; script-src 'sha256-${hash(script)}'; style-src 'sha256-${hash(style)}'; img-src data:; connect-src 'none'; media-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'`;
const html = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><style>${style}</style></head><body><canvas aria-label="Alex robot"></canvas><script>${script}</script></body></html>`;
fs.mkdirSync(path.join(root,'assets/robot-heads'),{recursive:true});
fs.writeFileSync(path.join(root,'assets/robot-heads/live.html'),html);
console.log(`Built offline renderer: ${Buffer.byteLength(html)} bytes; no external resources.`);

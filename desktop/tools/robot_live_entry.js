// This runs inside the private canvas, driven at most 30 fps by Qt.
const canvas = document.querySelector('canvas');
const context = canvas.getContext('2d');
const shape = geometry.getShape('circle');
const renderer = new render.RobotRenderer();
const robot = new sim.RobotSim(.37, 'idle');
const palette = {
  shell:{albedo:light.linear([37,151,145]), f0:.05, metal:.15, spec:.55, shininess:70, rim:.9},
  trim:{albedo:light.linear([167,212,211]), f0:.2, metal:.65, spec:.8, shininess:45, rim:.7},
  led:[219,255,244]
};
const states = new Set(['idle','listening','thinking','speaking','sleeping','error','happy','working','searching']);
let last = 0, active = false, draws = 0, totalMs = 0, state = 'idle', frame;
function tick(payload) {
  if (!payload.visible) { active=false; last=0; robot.pointer=null; return; }
  active = true;
  const start = performance.now();
  const dt = last ? Math.min(.25, Math.max(0,(start-last)/1000)) : 1/30;
  last = start;
  const size = Math.max(64, Math.min(320, Number(payload.size) || 110));
  frame = render.frameFor(shape, true, size);
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = Math.round((frame.box + 2*frame.padSide)*dpr);
  const h = Math.round((frame.box + frame.padTop + frame.padBottom)*dpr);
  if (canvas.width !== w || canvas.height !== h) { canvas.width=w; canvas.height=h; }
  canvas.style.width = (frame.box + 2*frame.padSide)+'px';
  canvas.style.height = (frame.box + frame.padTop + frame.padBottom)+'px';
  const p = payload.pointer;
  robot.pointer = payload.follow && p && Number.isFinite(p.x) && Number.isFinite(p.y)
    ? {x:Math.max(-1000,Math.min(1000,p.x-frame.cx)), y:Math.max(-1000,Math.min(1000,p.y-frame.cy))} : null;
  // Mic-off is independent of gaze. Awake eyes never imply that the mic is open.
  state = payload.state === 'paused' ? (payload.follow ? 'idle' : 'sleeping') : payload.state;
  if (!states.has(state)) state='idle';
  robot.setState(state);
  robot.update(dt);
  renderer.draw(context, frame, dpr, robot.pose, robot, state, shape, palette,
                {floorShadow:true, antenna:true});
  draws++;
  totalMs += performance.now()-start;
}
window.alexRobot = Object.freeze({
  tick,
  debug:() => ({ready:true,active,draws,state,pose:{...robot.pose},
               eyes:{x:robot.face.lookX,y:robot.face.lookY},
               pointer:robot.pointer,meanDrawMs:draws ? totalMs/draws : 0})
});

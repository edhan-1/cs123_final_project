// Checks for the fast ear's logic in play.html, without a browser:
//     node web/test_play.js
// The page's script runs here with a stand-in page, microphone, speech recogniser
// and robot. It checks what the ear tells the robot for what it hears. It cannot
// check the real microphone or the real speech recognition: that takes Chrome.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const code = fs.readFileSync(path.join(__dirname, 'play.html'), 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];

// ---- stand-ins
const told = [];       // everything posted to the robot: [path, body]
const ears = [];       // the speech recognisers the page started
const timers = [];     // the page's setInterval callbacks
const elements = {};
const element = id => elements[id] || (elements[id] = {
  style: {}, textContent: '', className: '', addEventListener() {},
  value: { sens: '55', distance: '3' }[id] || '',
});
global.document = { getElementById: element, addEventListener() {} };
global.localStorage = { getItem: () => null, setItem() {} };
global.navigator = { mediaDevices: { getUserMedia: async () => { throw new Error('no microphone here'); } } };
global.fetch = async (where, options) => {
  told.push([where, JSON.parse(options.body)]);
  return { json: async () => ({ success: true, message: 'ok' }) };
};
global.SpeechRecognition = class { start() { ears.push(this); setTimeout(() => this.onstart(), 0); } stop() {} };
global.setInterval = fn => timers.push(fn);
global.window = global;

vm.runInThisContext(code + `
;globalThis.page = { watchPupperVoice, pupperTalksFor(ms) { pupperSpeaksUntil = performance.now() + ms; },
                     get pupperSpeaksUntil() { return pupperSpeaksUntil; }, get wordEar() { return wordEar; } };`);

// ---- helpers
let failed = 0, passed = 0;
function check(name, ok, detail = '') {
  ok ? passed++ : failed++;
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : ': ' + detail}`);
}
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
const heard = () => told.filter(([where]) => where === '/game/heard').map(([, body]) => body.what);
/** Chrome's speech recognition reporting sentence number `index` as `text` (again and again, as it firms up). */
async function chromeHears(index, text) {
  ears.at(-1).onresult({ resultIndex: index, results: Object.assign([], { [index]: [{ transcript: text }] }) });
  await tick();
}

(async () => {
  await tick();
  console.log('The word ear');
  check('it starts with the page', ears.length === 1 && page.wordEar === 'on', `ears ${ears.length}, word ear ${page.wordEar}`);

  await chromeHears(0, 'green');
  check('"green" alone tells the robot nothing', heard().length === 0, heard().join());
  await chromeHears(0, 'green light');
  check('"green light" is a green light', heard().join() === 'green light', heard().join());
  await chromeHears(0, 'green light');
  await chromeHears(0, 'Green light.');
  check('the same sentence reported again is not a second green light', heard().join() === 'green light', heard().join());
  await chromeHears(0, 'green light red light');
  check('"red light" added to the sentence is a red light', heard().join() === 'green light,red light', heard().join());
  await chromeHears(1, 'green beans');
  await chromeHears(2, 'what a bright red');
  check('"green beans" and "red" alone are nothing', heard().length === 2, heard().join());
  await chromeHears(3, 'greenlight');
  await chromeHears(4, 'red lite');
  check('"greenlight" and "red lite" (how Chrome sometimes writes them) count', heard().slice(2).join() === 'green light,red light', heard().join());
  await chromeHears(5, 'green light red light green light');
  check('three calls in one breath: the last one wins', heard().at(-1) === 'green light' && heard().length === 5, heard().join());

  console.log("Pupper's own voice");
  const win = { AudioBufferSourceNode: function () {} };
  let played = 0;
  win.AudioBufferSourceNode.prototype.start = function () { played++; };
  page.watchPupperVoice(win);
  page.watchPupperVoice(win);  // the frame loaded again: must not wrap twice
  const piece = new win.AudioBufferSourceNode();
  Object.assign(piece, { context: { currentTime: 10 }, buffer: { duration: 2 } });
  piece.start(10.5);  // the app queues a 2 s piece of Pupper's voice, starting in 0.5 s
  const talksFor = page.pupperSpeaksUntil - performance.now();
  check('the app still plays the sound, once', played === 1, `played ${played}`);
  check('the page knows Pupper talks for the next 2.5 s', Math.abs(talksFor - 2500) < 50, `${talksFor.toFixed(0)} ms`);
  const before = heard().length;
  await chromeHears(6, 'say green light and i go');
  check('"green light" in Pupper\'s own voice is not a green light', heard().length === before, heard().slice(before).join());
  check('... and the bar says why', /Pupper talking/.test(element('status').textContent), element('status').textContent);
  await chromeHears(7, 'red light');
  check('"red light" while Pupper talks still stops it', heard().at(-1) === 'red light' && heard().length === before + 1, heard().slice(before).join());
  page.pupperTalksFor(-1001);  // Pupper stopped talking a second ago
  await chromeHears(8, 'green light');
  check('a second after Pupper stops, "green light" counts again', heard().at(-1) === 'green light', heard().slice(before).join());

  console.log('The rest of the bar');
  const said = heard().length;
  timers.forEach(fn => fn());
  await tick();
  check('every 2 s the page says the word ear is listening', heard().slice(said).join() === 'listening', heard().slice(said).join());
  element('distance').value = '5';
  await element('new').onclick();
  check('New game starts a game with the distance in the box',
        JSON.stringify(told.at(-1)) === JSON.stringify(['/tools/start_game', { distance: 5 }]), JSON.stringify(told.at(-1)));
  element('mode').value = 'off';
  element('mode').onchange();
  const quiet = heard().length;
  timers.forEach(fn => fn());
  await chromeHears(9, 'green light');
  await tick();
  check('"nothing" really is nothing: no "listening"', !heard().slice(quiet).includes('listening'), heard().slice(quiet).join());

  console.log(failed ? `\n${failed} check(s) failed, ${passed} passed.` : `\nAll ${passed} checks passed.`);
  process.exit(failed ? 1 : 0);
})();

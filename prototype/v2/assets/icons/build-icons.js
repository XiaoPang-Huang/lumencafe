const fs = require('fs');
const map = {
  home: 'house', chat: 'message-circle', money: 'wallet', grid: 'grid-2x2',
  gear: 'settings', user: 'user', search: 'search', plus: 'plus', send: 'send',
  close: 'x', menu: 'menu', book: 'book-open', copy: 'copy', trash: 'trash-2',
  edit: 'pencil', arrow: 'arrow-right', logout: 'log-out', shield: 'shield-check',
  plug: 'plug', spark: 'sparkles', calendar: 'calendar', lock: 'lock',
  doc: 'file-text', chart: 'bar-chart-3', check: 'check', key: 'key-round',
  users: 'users', grip: 'grip-vertical', eye: 'eye', clip: 'paperclip',
  down: 'chevron-down', token: 'key-round', logo: 'coffee'
};
const out = {};
const missing = [];
for (const k of Object.keys(map)) {
  const f = map[k];
  try {
    const raw = fs.readFileSync(f + '.svg', 'utf8');
    const start = raw.indexOf('>', raw.indexOf('<svg')) + 1;
    const end = raw.lastIndexOf('</svg>');
    out[k] = raw.slice(start, end).trim().replace(/\s+/g, ' ');
    if (!out[k]) missing.push(k + '(empty)');
  } catch (e) { missing.push(k + ':' + e.code); }
}
const body = Object.keys(out).map(k => '  "' + k + '": ' + JSON.stringify(out[k])).join(',\n');
fs.writeFileSync('../js/icons.js',
  '/* Lucide icons (ISC) — 本地化为内联 SVG，生成自 lucide-static@0.545.0，勿手改 */\nwindow.LC_ICONS = {\n' + body + '\n};\n');
console.log('icons:', Object.keys(out).length, '| missing:', missing.join(',') || 'none');

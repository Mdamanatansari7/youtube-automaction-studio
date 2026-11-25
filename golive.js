// Go Live panel: stream a video to YouTube / Facebook / Twitch / any RTMP server as a Shorts (9:16) or landscape (16:9) live,
// with the same layouts and facecam boxes as Shorts, plus a logo and banner that can be changed while live. Server side: golive.py.
(function () {
  const $ = id => document.getElementById(id);
  if (!$('golive-panel')) return;
  const HELP = {
    youtube_auto: 'Fully automatic: the app creates the live on your connected channel, streams the video, and ends the live when you press Stop. No stream key needed. Choose Shorts · 9:16 for a vertical live in the Shorts feed.',
    youtube: 'YouTube Studio → Create → Go live → Stream → copy the Stream key. For a vertical live in the Shorts feed choose Shorts · 9:16.',
    facebook: 'Facebook: Live Producer → Streaming software → copy the Stream key.',
    twitch: 'Twitch: Creator Dashboard → Settings → Stream → Primary stream key.',
    custom: 'Paste the RTMP / RTMPS server address and the stream key from your platform (Instagram Live Producer, Kick, Restream…).'
  };
  let liveId = null, timer = null, logoId = null, bannerId = null, yt = null;
  const STORE = 'ns_golive_v2';

  async function request(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw Error(j.detail || 'Request failed');
    return j;
  }
  const msg = (t, bad) => { $('gl-msg').textContent = t || ''; $('gl-msg').style.color = bad ? '#ff7a90' : ''; };
  const clock = s => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 3600) + ':' + String(Math.floor(s / 60) % 60).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); };

  // ---- saved choices (never the key unless "remember" is ticked)
  const SAVE = ['gl-crop', 'gl-format', 'gl-layout', 'gl-quality', 'gl-fps', 'gl-logo-pos', 'gl-logo-size', 'gl-banner-text', 'gl-banner-pos', 'gl-banner-bg', 'gl-banner-color', 'gl-platform', 'gl-server', 'gl-title', 'gl-privacy', 'gl-desc'];
  function saveChoices() {
    const o = { logoId, bannerId, loop: $('gl-loop').checked, remember: $('gl-remember').checked };
    SAVE.forEach(k => o[k] = $(k).value);
    try { localStorage.setItem(STORE, JSON.stringify(o)); } catch (e) {}
    try { if ($('gl-remember').checked && $('gl-key').value) localStorage.setItem('ns_golive_key_' + $('gl-platform').value, $('gl-key').value); else localStorage.removeItem('ns_golive_key_' + $('gl-platform').value); } catch (e) {}
  }
  function loadChoices() {
    let o = {};
    try { o = JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) {}
    SAVE.forEach(k => { if (o[k] !== undefined && o[k] !== null) $(k).value = o[k]; });
    if (o.loop === false) $('gl-loop').checked = false;
    $('gl-remember').checked = !!o.remember;
    logoId = o.logoId || null; bannerId = o.bannerId || null;
    $('gl-logo-name').textContent = logoId ? 'Logo uploaded ✓' : 'No logo';
    $('gl-banner-name').textContent = bannerId ? 'Banner image uploaded ✓' : 'No banner image';
    loadKey();
  }
  // Earlier versions saved "crop" or "My layout" as the Go Live layout by default; switch those once to "Same as step 02".
  function layoutMigrated() {
    try {
      if (localStorage.getItem('ns_golive_layout_v3')) return $('gl-layout').value !== '';     // '' = a saved value that no longer exists
      localStorage.setItem('ns_golive_layout_v3', '1');
    } catch (e) {}
    return false;
  }
  function loadKey() { try { $('gl-key').value = localStorage.getItem('ns_golive_key_' + $('gl-platform').value) || ''; } catch (e) {} }
  function platformUI() {
    const p = $('gl-platform').value, auto = p === 'youtube_auto';
    $('gl-server-wrap').hidden = p !== 'custom';
    $('gl-key-wrap').hidden = $('gl-remember-wrap').hidden = auto;
    $('gl-auto').hidden = !auto;
    $('gl-help').textContent = HELP[p];
    if (auto) ytCheck();
  }

  // ---- the connected YouTube channel (same connection the uploads use)
  /** The channel this live goes to: the one picked in "Channel" (shown with 2+ channels), else the active one. */
  function chosen() {
    const list = (yt && Array.isArray(yt.channels)) ? yt.channels : [];
    const pick = list.find(c => c.id === $('gl-channel').value) || list.find(c => c.active);
    if (pick) return pick;
    return yt && yt.connected ? { id: '', title: (yt.channel && yt.channel.title) || 'your channel', live_allowed: !!yt.live_allowed } : null;
  }
  async function ytCheck(refetch = true) {
    const state = $('gl-yt-state'), btn = $('gl-yt-connect');
    if (refetch) { try { yt = await request('/youtube/status'); } catch (e) { yt = null; } }
    btn.hidden = false;
    const ch = chosen();
    if (!yt || !yt.connected || !ch) {
      state.textContent = '⚠ No YouTube channel connected yet.'; state.className = 'gl-yt-bad';
      btn.textContent = '▶ Connect YouTube'; btn.dataset.action = 'connect';
    } else if (!ch.live_allowed) {
      state.textContent = '✓ Connected: ' + (ch.title || 'your channel') + ' · live permission is still needed (one time).'; state.className = 'gl-yt-warn';
      btn.textContent = '🔓 Allow live streaming'; btn.dataset.action = 'allow';
    } else {
      state.textContent = '✓ Ready to go live on ' + (ch.title || 'your channel'); state.className = 'gl-yt-ok';
      btn.hidden = true;
    }
  }
  async function ytConnect() {
    if ($('gl-yt-connect').dataset.action === 'connect' || !yt || !yt.has_secrets) {
      if (window.NeonYouTube && window.NeonYouTube.openSettings) window.NeonYouTube.openSettings();
      return;
    }
    try {
      const j = await request('/youtube/auth-url');
      const w = window.open(j.url, '_blank', 'width=600,height=700');
      if (!w) location.href = j.url;
      msg('Pick the same channel and allow everything YouTube asks. Come back here when the window says "Connected".');
    } catch (e) { msg(e.message, true); }
  }

  async function upload(input, label, done) {
    const f = input.files[0]; if (!f) return;
    const form = new FormData(); form.append('file', f);
    label.textContent = 'Uploading…';
    try {
      const r = await fetch('/upload-asset?kind=image', { method: 'POST', body: form }); const j = await r.json();
      if (!r.ok) throw Error(j.detail || 'Upload failed');
      done(j.id); label.textContent = (f.name || 'Image').slice(0, 40) + ' ✓'; saveChoices();
      if (liveId) updateOverlay();
    } catch (e) { label.textContent = e.message; }
  }

  function overlay() {
    return { logo: logoId || '', logo_pos: $('gl-logo-pos').value, logo_size: Number($('gl-logo-size').value), show_logo: $('gl-show-logo').checked,
      banner_text: $('gl-banner-text').value, banner_image: bannerId || '', banner_pos: $('gl-banner-pos').value,
      banner_bg: $('gl-banner-bg').value, banner_color: $('gl-banner-color').value, show_banner: $('gl-show-banner').checked };
  }
  function body(test) {
    const b = { test, format: $('gl-format').value, quality: Number($('gl-quality').value), fps: Number($('gl-fps').value), loop: $('gl-loop').checked,
      platform: $('gl-platform').value, server: $('gl-server').value.trim(), key: $('gl-key').value.trim(),
      title: $('gl-title').value.trim(), description: $('gl-desc').value, privacy: $('gl-privacy').value,
      channel: $('gl-channel').value || '', ...overlay() };
    const url = $('gl-url').value.trim();
    if ($('gl-use-loaded').checked || !url) {
      if (typeof id === 'undefined' || !id) throw Error('Paste a video link above, or load a video in step 01 and tick "Use the video loaded above".');
      b.id = id;
    } else b.url = url;
    b.layout = effectiveLayout();
    b.crop = Number($('gl-crop').value);
    if (typeof rect !== 'undefined') { b.cam = rect.cam; b.game = rect.game; }
    // Face boxes drawn in step 03 belong to the video loaded above. For any other link the app finds the facecam itself.
    b.cam_auto = !(b.id && typeof rectEdited !== 'undefined' && rectEdited);
    if ($('top')) b.top = Number($('top').value) / 100;
    if ($('gl-cam').checked) {
      if (!window.customCamId) throw Error('Upload your facecam video in step 03 first, or untick "Add my own facecam video".');
      b.custom_cam = window.customCamId;
    }
    return b;
  }

  async function start(test) {
    msg('');
    let b;
    try { b = body(test); } catch (e) { msg(e.message, true); return; }
    const auto = b.platform === 'youtube_auto';
    if (!test && auto) {
      await ytCheck();
      if (!yt || !yt.connected || !chosen()) { msg('Connect your YouTube channel first (button above).', true); return; }
      if (!chosen().live_allowed) { msg('Press "🔓 Allow live streaming" once for ' + (chosen().title || 'this channel') + ', then Go live.', true); return; }
      if (!b.title) { msg('Give the live a title.', true); $('gl-title').focus(); return; }
    }
    if (!test && !auto && !b.key && b.platform !== 'custom') { msg('Paste your stream key first. ' + HELP[b.platform], true); $('gl-key').focus(); return; }
    const where = auto ? ((chosen() && chosen().title) || 'your YouTube channel') + ' as ' + $('gl-privacy').selectedOptions[0].text : $('gl-platform').selectedOptions[0].text;
    if (!test && !confirm('Go live now on ' + where + '?' + (b.privacy === 'public' || !auto ? ' Viewers will see it.' : '') + '\n\nOnly stream videos you own or have permission to use, or the platform can strike your channel.')) return;
    saveChoices();
    $('gl-start').disabled = $('gl-test').disabled = true;
    try {
      const r = await request('/golive/start', b);
      attach(r.live);
    } catch (e) { msg(e.message, true); }
    finally { $('gl-start').disabled = $('gl-test').disabled = false; }
  }

  function setupVisible(on) {
    $('gl-source').hidden = $('gl-dest').hidden = $('gl-actions').hidden = !on;
    $('gl-manage').hidden = false;
  }
  function attach(lid) {
    liveId = lid; setupVisible(false); $('gl-new').hidden = true; $('gl-stop').hidden = false; $('gl-update').hidden = false; $('gl-links').hidden = true;
    $('gl-preview').hidden = true; $('gl-preview').removeAttribute('src');
    clearInterval(timer); timer = setInterval(poll, 1000); poll();
  }
  const LABEL = { starting: '⏳ Preparing…', downloading: '⬇ Downloading the video…', connecting: '⏳ Connecting…', live: '🔴 LIVE', reconnecting: '⚠ Reconnecting…',
    testing: '🧪 Test running…', done: '✓ Finished', stopped: '■ Stopped', error: '✕ Stopped with an error' };
  async function poll() {
    if (!liveId) return;
    let s;
    try { s = await request('/golive/' + liveId); } catch (e) { msg(e.message, true); clearInterval(timer); finished(); return; }
    const running = ['starting', 'downloading', 'connecting', 'live', 'reconnecting', 'testing'].includes(s.status);
    $('gl-state').textContent = (LABEL[s.status] || s.status) + ' · ' + s.destination + (s.status === 'live' ? ' · ' + clock(s.elapsed) : '');
    $('gl-state').className = 'gl-state-' + s.status;
    const bits = [s.stage, s.size + ' @ ' + s.fps_target + ' fps', s.layout];
    if (s.facecam) bits.push(s.facecam);
    if (s.youtube) bits.push('YouTube: ' + ({ created: 'live created', ready: 'waiting for video', testing: 'starting…', testStarting: 'starting…', liveStarting: 'going live…', live: 'LIVE', complete: 'ended' }[s.youtube] || s.youtube));
    if (s.watch_url) { $('gl-links').hidden = false; $('gl-watch').href = s.watch_url; $('gl-studio').href = s.studio_url || s.watch_url; }
    if (['live', 'reconnecting', 'testing'].includes(s.status) || s.frames) bits.push('video at ' + clock(s.position) + (s.duration ? ' / ' + clock(s.duration) : ''), (s.fps ? Math.round(s.fps) + ' fps now' : ''), s.bitrate, s.test && s.speed ? 'speed ' + s.speed : '', s.dropped ? s.dropped + ' dropped frames' : '', s.reconnects ? s.reconnects + ' reconnects' : '', s.encoder);
    $('gl-stats').textContent = bits.filter(Boolean).join(' · ');
    if (s.error) msg(s.error, true);
    if (s.status === 'done' && s.preview) {
      const v = $('gl-preview'); if (!v.getAttribute('src')) { v.src = s.preview + '?t=' + Date.now(); v.hidden = false; }
      msg('Test ready. Your computer rendered it at ' + (s.speed || '?') + ' real-time speed' + (parseFloat(s.speed) >= 1.3 ? ', fast enough to go live.' : '. If it is under 1.3x, choose 720p before going live.'));
    }
    if (!running) { clearInterval(timer); finished(); }
  }
  function finished() { $('gl-stop').hidden = true; $('gl-update').hidden = true; $('gl-new').hidden = false; }

  async function updateOverlay() {
    if (!liveId) return;
    saveChoices();
    try { await request('/golive/' + liveId + '/overlay', overlay()); msg('Logo & banner updated. Viewers see it in a few seconds.'); }
    catch (e) { msg(e.message, true); }
  }

  // ---- follow step 02 "Make it your format"
  const NAMES = { stack: 'Face + gameplay', bottom: 'Gameplay + face', blur: 'Blurred fill', fill: 'Fill screen (crop)', game: 'Gameplay only',
    pip_tl: 'Camera top-left', pip_tr: 'Camera top-right', pip_bl: 'Camera bottom-left', pip_br: 'Camera bottom-right', circle: 'Circle camera', side: 'Side by side' };
  const FACE = ['stack', 'bottom', 'pip_tl', 'pip_tr', 'pip_bl', 'pip_br', 'circle', 'side'];
  const stepTwo = () => (typeof layout !== 'undefined' && NAMES[layout]) ? layout : 'stack';     // what is highlighted in step 02
  function effectiveLayout() { return $('gl-layout').value === 'step2' ? stepTwo() : $('gl-layout').value; }
  function layoutUI() {
    const two = stepTwo();
    $('gl-layout').options[0].textContent = 'Same as step 02 · ' + NAMES[two];
    const eff = effectiveLayout(), wide = $('gl-format').value === 'landscape';
    const usingLoaded = $('gl-use-loaded').checked || !$('gl-url').value.trim();
    let note = '';
    if (FACE.includes(eff)) note = usingLoaded && typeof rectEdited !== 'undefined' && rectEdited
      ? '🙂 Face: using the facecam box you drew in step 03.'
      : '🙂 Face: the app finds the facecam in this video by itself. If the video has no facecam it fills the screen without one.';
    if (wide && ['stack', 'bottom', 'circle'].includes(eff)) note = 'Landscape cannot stack the face above the game, so it shows the full video. Pick a facecam-corner format in step 02 for a face in landscape.';
    $('gl-face-note').textContent = note;
    cropUI();
  }
  function cropUI() {
    const v = Number($('gl-crop').value);
    $('gl-crop-o').textContent = v <= 10 ? 'Left' : v >= 90 ? 'Right' : v === 50 ? 'Centre' : (v < 50 ? 'Left of centre' : 'Right of centre') + ' (' + v + '%)';
    $('gl-crop-wrap').hidden = effectiveLayout() !== 'fill';
  }

  // ---- wiring
  loadChoices(); platformUI();
  if (!layoutMigrated()) $('gl-layout').value = 'step2';
  layoutUI();
  $('gl-crop').oninput = cropUI;
  $('gl-layout').addEventListener('change', () => { layoutUI(); saveChoices(); });
  ['gl-format', 'gl-use-loaded', 'gl-url'].forEach(k => $(k).addEventListener('change', layoutUI));
  // clicking a format in step 02 (or editing the boxes in step 03) updates the Go Live choice right away
  document.addEventListener('click', e => { if (e.target.closest && e.target.closest('[data-layout], .choice, #frames, #canvas')) setTimeout(layoutUI, 50); });
  document.addEventListener('pointerup', () => setTimeout(layoutUI, 80));
  $('gl-crop').addEventListener('change', saveChoices);
  $('gl-platform').onchange = () => { platformUI(); loadKey(); saveChoices(); };
  $('gl-logo-size').oninput = () => { $('gl-logo-size-o').textContent = $('gl-logo-size').value + '%'; };
  $('gl-logo-size').oninput();
  $('gl-logo-file').onchange = () => upload($('gl-logo-file'), $('gl-logo-name'), v => logoId = v);
  $('gl-banner-file').onchange = () => upload($('gl-banner-file'), $('gl-banner-name'), v => bannerId = v);
  ['gl-show-logo', 'gl-show-banner', 'gl-logo-pos', 'gl-banner-pos', 'gl-banner-bg', 'gl-banner-color'].forEach(k => $(k).addEventListener('change', () => { saveChoices(); if (liveId && $('gl-stop').hidden === false) updateOverlay(); }));
  $('gl-logo-size').addEventListener('change', () => { saveChoices(); if (liveId && !$('gl-stop').hidden) updateOverlay(); });
  $('gl-test').onclick = () => start(true);
  $('gl-start').onclick = () => start(false);
  $('gl-update').onclick = updateOverlay;
  $('gl-stop').onclick = async () => {
    if (!liveId || !confirm('Stop now?')) return;
    try { await request('/golive/' + liveId + '/stop', {}); } catch (e) { msg(e.message, true); }
    poll();
  };
  $('gl-new').onclick = () => { liveId = null; setupVisible(true); $('gl-manage').hidden = true; msg(''); };
  $('gl-remember').onchange = saveChoices;
  $('gl-yt-connect').onclick = ytConnect;
  $('gl-channel').addEventListener('change', () => ytCheck(false));
  window.addEventListener('yt-status', () => { if ($('gl-platform').value === 'youtube_auto' && !liveId) ytCheck(); });
  ['gl-title', 'gl-privacy', 'gl-desc'].forEach(k => $(k).addEventListener('change', saveChoices));
  window.addEventListener('message', e => { if (e.data === 'youtube_connected') { ytCheck(); msg('YouTube connected. You can go live now.'); } });
  window.addEventListener('focus', () => { if ($('gl-platform').value === 'youtube_auto' && !liveId) ytCheck(); });
  $('gl-key').onchange = saveChoices;
  // Back on the page after a reload while a live is running: show its controls again.
  request('/golive-active').then(r => { if (r.live) attach(r.live); }).catch(() => {});
})();

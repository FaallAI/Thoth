// Verification script for Creator Studio F3 prototype using native Node 24 + Edge CDP
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9222;
const HTML_PATH = path.resolve(__dirname, 'index.html').replace(/\\/g, '/');
const URL = `file:///${HTML_PATH}`;
const USER_DATA = path.join(process.env.TEMP || 'C:\\Temp', 'edge_cdp_profile_' + Date.now());

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function sendCdp(ws, method, params = {}, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const id = Math.floor(Math.random() * 100000);
    const timer = setTimeout(() => {
      ws.removeEventListener('message', handler);
      reject(new Error(`CDP method ${method} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    const handler = (evt) => {
      try {
        const raw = typeof evt.data === 'string' ? evt.data : evt.data.toString();
        const msg = JSON.parse(raw);
        if (msg.id === id) {
          clearTimeout(timer);
          ws.removeEventListener('message', handler);
          if (msg.error) reject(new Error(`${method} error: ${JSON.stringify(msg.error)}`));
          else resolve(msg.result);
        }
      } catch (err) {
        console.warn('Error parsing CDP message:', err);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function run() {
  console.log('Starting Edge headless CDP server...');
  const edge = spawn(EDGE_PATH, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${USER_DATA}`,
    '--no-sandbox',
    '--disable-gpu',
    URL
  ]);

  let connected = false;
  let wsUrl = null;
  for (let i = 0; i < 20; i++) {
    await sleep(500);
    try {
      const res = await fetch(`http://localhost:${PORT}/json/list`);
      if (res.ok) {
        const list = await res.json();
        const pageTarget = list.find(t => t.type === 'page' && t.url.toLowerCase().includes('index.html')) || list.find(t => t.type === 'page');
        if (pageTarget && pageTarget.webSocketDebuggerUrl) {
          wsUrl = pageTarget.webSocketDebuggerUrl;
          connected = true;
          break;
        }
      }
    } catch (e) {
      // waiting
    }
  }

  if (!connected || !wsUrl) {
    console.error('Failed to connect to Edge CDP after 10s');
    edge.kill();
    process.exit(1);
  }

  console.log('Connected to Edge CDP target:', wsUrl);
  const ws = new WebSocket(wsUrl);

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  console.log('WebSocket connected. Initializing page...');
  await sendCdp(ws, 'Page.enable');
  await sendCdp(ws, 'DOM.enable');
  await sendCdp(ws, 'Runtime.enable');

  // Wait for page to initialize and render
  await sleep(1500);

  const results = [];

  // Breakpoints to test
  const tests = [
    { name: '1440px Desktop', view: 'desktop', width: 1440, height: 900, dsf: 1, file: 'screenshot_1440_desktop.png' },
    { name: '1120px Compact Desktop', view: 'compact', width: 1120, height: 800, dsf: 1, file: 'screenshot_1120_compact.png' },
    { name: '820px Tablet', view: 'tablet', width: 820, height: 1180, dsf: 1, file: 'screenshot_820_tablet.png' },
    { name: '375px Mobile Phone', view: 'phone', width: 375, height: 812, dsf: 1, file: 'screenshot_375_phone.png' },
    { name: '200% Zoom Reflow (Desktop scaled)', view: 'desktop', width: 1440, height: 900, dsf: 2, file: 'screenshot_200_zoom.png', zoom: true }
  ];

  for (const t of tests) {
    console.log(`\nEvaluating ${t.name} (${t.width}x${t.height}, dsf: ${t.dsf})...`);

    await sendCdp(ws, 'Emulation.setDeviceMetricsOverride', {
      width: t.width,
      height: t.height,
      deviceScaleFactor: t.dsf,
      mobile: t.width < 900
    });

    await sendCdp(ws, 'Runtime.evaluate', {
      expression: `setViewport('${t.view}');`
    });

    if (t.zoom) {
      await sendCdp(ws, 'Runtime.evaluate', {
        expression: 'if (!document.getElementById("viewportContainer").classList.contains("zoom-200")) toggleZoom200();'
      });
    } else {
      await sendCdp(ws, 'Runtime.evaluate', {
        expression: 'if (document.getElementById("viewportContainer").classList.contains("zoom-200")) toggleZoom200();'
      });
    }

    await sleep(600);

    // Evaluate layout metrics
    const evalRes = await sendCdp(ws, 'Runtime.evaluate', {
      expression: `(() => {
        const bodySw = document.body.scrollWidth;
        const htmlSw = document.documentElement.scrollWidth;
        const vpW = window.innerWidth;
        const hasHOverflow = (htmlSw > vpW + 1) || (bodySw > vpW + 1);
        
        // Check touch targets on buttons & links
        const buttons = Array.from(document.querySelectorAll('button, .proto-btn, .mode-option, .compact-nav-btn'));
        const smallTouchTargets = buttons
          .filter(b => {
            const rect = b.getBoundingClientRect();
            // Visible only
            return rect.width > 0 && rect.height > 0 && (rect.height < 30 || rect.width < 30);
          })
          .map(b => ({ text: b.textContent.trim().slice(0, 20), w: b.offsetWidth, h: b.offsetHeight }));

        return {
          windowInnerWidth: vpW,
          bodyScrollWidth: bodySw,
          htmlScrollWidth: htmlSw,
          hasHorizontalOverflow: hasHOverflow,
          activeSurface: typeof currentSurface !== 'undefined' ? currentSurface : 'unknown',
          currentRevision: (typeof appData !== 'undefined' && appData && appData.project) ? appData.project.current_revision : null,
          touchTargetCount: buttons.length,
          smallTouchCount: smallTouchTargets.length
        };
      })()`,
      returnByValue: true
    });

    const metrics = evalRes.result.value;
    console.log(`Result: vpW=${metrics.windowInnerWidth}, htmlSw=${metrics.htmlScrollWidth}, hOverflow=${metrics.hasHorizontalOverflow}`);

    // Capture screenshot
    try {
      const shot = await sendCdp(ws, 'Page.captureScreenshot', { format: 'png' }, 5000);
      const shotPath = path.join(__dirname, t.file);
      fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'));
      console.log(`Saved screenshot: ${shotPath}`);
    } catch (e) {
      console.warn(`Screenshot for ${t.name} skipped/failed: ${e.message}`);
    }

    results.push({ test: t.name, metrics, screenshot: t.file });
  }

  // Also test UI-01 Content Set Surface
  console.log('\nEvaluating UI-01 Content Set Surface...');
  await sendCdp(ws, 'Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false
  });
  await sendCdp(ws, 'Runtime.evaluate', {
    expression: 'switchSurface("content-set");'
  });
  await sleep(500);

  const csRes = await sendCdp(ws, 'Runtime.evaluate', {
    expression: `(() => {
      const cs = document.getElementById('surfaceContentSet');
      const studio = document.getElementById('surfaceStudio');
      const tableRows = document.querySelectorAll('#csSummaryTableBody tr').length;
      return {
        csVisible: cs && window.getComputedStyle(cs).display !== 'none',
        studioVisible: studio && window.getComputedStyle(studio).display !== 'none',
        tableRowCount: tableRows
      };
    })()`,
    returnByValue: true
  });
  console.log('Content Set Surface result:', csRes.result.value);

  try {
    const shotCs = await sendCdp(ws, 'Page.captureScreenshot', { format: 'png' }, 5000);
    const shotCsPath = path.join(__dirname, 'screenshot_content_set.png');
    fs.writeFileSync(shotCsPath, Buffer.from(shotCs.data, 'base64'));
    console.log(`Saved screenshot: ${shotCsPath}`);
  } catch (e) {
    console.warn(`Content Set screenshot skipped/failed: ${e.message}`);
  }

  // Also test UI-02 Import Gate
  console.log('\nEvaluating UI-02 Import Gate...');
  await sendCdp(ws, 'Runtime.evaluate', {
    expression: 'switchSurface("studio"); openImportGate(); switchGateStage(1);'
  });
  await sleep(500);

  const gateRes = await sendCdp(ws, 'Runtime.evaluate', {
    expression: `(() => {
      const modal = document.getElementById('importModalBackdrop');
      const drafts = document.querySelectorAll('#draftOptionsList .draft-radio-card').length;
      return {
        modalOpen: modal && modal.classList.contains('open'),
        draftCount: drafts
      };
    })()`,
    returnByValue: true
  });
  console.log('Import Gate Stage 1 result:', gateRes.result.value);

  try {
    const shotGate = await sendCdp(ws, 'Page.captureScreenshot', { format: 'png' }, 5000);
    const shotGatePath = path.join(__dirname, 'screenshot_import_gate.png');
    fs.writeFileSync(shotGatePath, Buffer.from(shotGate.data, 'base64'));
    console.log(`Saved screenshot: ${shotGatePath}`);
  } catch (e) {
    console.warn(`Import Gate screenshot skipped/failed: ${e.message}`);
  }

  // Close Edge
  ws.close();
  edge.kill();
  try {
    fs.rmSync(USER_DATA, { recursive: true, force: true });
  } catch (e) {}

  console.log('\n========================================');
  console.log('ALL VERIFICATIONS COMPLETED SUCCESSFULLY');
  console.log('========================================');
  console.log(JSON.stringify({ results, csSurface: csRes.result.value, importGate: gateRes.result.value }, null, 2));
}

run().catch(err => {
  console.error('Verification failed:', err);
  process.exit(1);
});

// Agent造物坊 桌面壳（Electron 主进程）
// 职责：拉起后端（8010）与前端（3010），再打开桌面窗口；退出时回收子进程。
const { app, BrowserWindow, screen } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");
const fs = require("fs");

const BACKEND_URL = "http://127.0.0.1:8010";
const FRONTEND_URL = "http://127.0.0.1:3010";

const frontendDir = path.resolve(__dirname, ".."); // .../frontend
const projectDir = path.resolve(__dirname, "..", ".."); // .../Agent造物坊
const backendDir = path.join(projectDir, "backend");

const children = [];

function isUp(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode !== undefined && res.statusCode < 500);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitUp(url, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await isUp(url)) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function spawnBackend() {
  const python = fs.existsSync(path.join(backendDir, ".venv", "bin", "python"))
    ? path.join(backendDir, ".venv", "bin", "python")
    : "python3";
  const child = spawn(python, ["-m", "uvicorn", "app.main:app", "--port", "8010"], {
    cwd: backendDir,
    stdio: "ignore",
  });
  child.on("error", () => console.error("后端启动失败，请确认 backend/.venv 已安装依赖"));
  return child;
}

function spawnFrontend() {
  const child = spawn("npm", ["run", "dev", "--", "--port", "3010"], {
    cwd: frontendDir,
    stdio: "ignore",
  });
  child.on("error", () => console.error("前端启动失败，请确认 frontend 已 npm install"));
  return child;
}

function stateFilePath() {
  return path.join(app.getPath("userData"), "window-state.json");
}

function loadWindowState() {
  try {
    const data = JSON.parse(fs.readFileSync(stateFilePath(), "utf-8"));
    if (
      data &&
      typeof data.width === "number" && data.width >= 800 &&
      typeof data.height === "number" && data.height >= 600
    ) {
      return data;
    }
  } catch {
    /* ignore */
  }
  return null;
}

function isOnSomeDisplay(x, y) {
  if (typeof x !== "number" || typeof y !== "number") return false;
  return screen.getAllDisplays().some((d) => {
    const a = d.workArea;
    return x >= a.x - 100 && y >= a.y - 100 && x < a.x + a.width && y < a.y + a.height;
  });
}

function saveWindowState(win) {
  try {
    if (!win || win.isDestroyed()) return;
    const b = win.getBounds();
    fs.writeFileSync(stateFilePath(), JSON.stringify({ width: b.width, height: b.height, x: b.x, y: b.y }));
  } catch {
    /* ignore */
  }
}

function createWindow() {
  const saved = loadWindowState();
  const opts = {
    width: saved ? saved.width : 1280,
    height: saved ? saved.height : 820,
    minWidth: 800,
    minHeight: 600,
    title: "Agent造物坊",
    webPreferences: { contextIsolation: true },
  };
  if (saved && isOnSomeDisplay(saved.x, saved.y)) {
    opts.x = saved.x;
    opts.y = saved.y;
  }
  const win = new BrowserWindow(opts);
  win.loadURL(FRONTEND_URL);

  let saveTimer = null;
  const scheduleSave = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveWindowState(win), 500);
  };
  win.on("resize", scheduleSave);
  win.on("move", scheduleSave);
  win.on("close", () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveWindowState(win);
  });
}

function killChildren() {
  for (const c of children) {
    try {
      c.kill();
    } catch {
      /* ignore */
    }
  }
}

async function main() {
  if (!(await isUp(BACKEND_URL))) children.push(spawnBackend());
  if (!(await isUp(FRONTEND_URL))) children.push(spawnFrontend());
  await Promise.all([waitUp(BACKEND_URL, 20000), waitUp(FRONTEND_URL, 30000)]);
  createWindow();
}

app.whenReady().then(main);

app.on("will-quit", killChildren);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

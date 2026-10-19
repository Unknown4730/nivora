import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import { platform } from "node:os";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const isWindows = platform() === "win32";
const python = resolve(root, isWindows ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const backendPort = 8000;

if (!existsSync(python)) {
  console.error(`Python virtual environment not found at ${python}. Run the setup command from README.md first.`);
  process.exit(1);
}

function portIsAvailable(port) {
  return new Promise((resolvePort) => {
    const probe = net.createServer();
    probe.once("error", () => resolvePort(false));
    probe.once("listening", () => probe.close(() => resolvePort(true)));
    probe.listen(port, "127.0.0.1");
  });
}

if (!(await portIsAvailable(backendPort))) {
  console.error(`Port ${backendPort} is already in use. Stop the existing AURA-Med backend, then run npm run dev again.`);
  console.error(isWindows ? "PowerShell: Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess" : "Linux/macOS: lsof -i :8000");
  process.exit(1);
}

const processes = [];
const command = (file, args, options = {}) => {
  const child = spawn(file, args, {
    cwd: root,
    env: { ...process.env, PYTHONPATH: "backend", ...options.env },
    stdio: "inherit",
    // npm is a Windows command shim; use the platform shell only there so
    // the same runner works on PowerShell, cmd.exe, and POSIX shells.
    shell: isWindows,
  });
  processes.push(child);
  child.on("exit", (code, signal) => {
    if (!shuttingDown && code !== 0) {
      console.error(`${file} exited with ${signal || `code ${code}`}. Stopping the other process.`);
      shutdown(code || 1);
    }
  });
  return child;
};

let shuttingDown = false;
function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of processes) {
    if (!child.killed) child.kill();
  }
  setTimeout(() => process.exit(code), 150);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

console.log("Starting AURA-Med backend at http://127.0.0.1:8000");
console.log("Starting AURA-Med frontend at http://localhost:5173");
console.log("Press Ctrl+C once to stop both processes.");

command(python, ["-m", "uvicorn", "aura_med.api.main:app", "--host", "127.0.0.1", "--port", "8000"]);
command(isWindows ? "npm.cmd" : "npm", ["--prefix", "frontend", "run", "dev"]);

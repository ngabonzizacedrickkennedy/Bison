import { app, BrowserWindow } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { config } from "./config";

const currentDir = path.dirname(fileURLToPath(import.meta.url));

const createWindow = async (): Promise<void> => {
  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    backgroundColor: "#111111",
    webPreferences: {
      preload: path.join(currentDir, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  window.once("ready-to-show", () => {
    window.show();
  });

  if (config.isDevelopment) {
    await window.loadURL(`http://127.0.0.1:${config.devServerPort}`);
    window.webContents.openDevTools({ mode: "detach" });
    return;
  }

  await window.loadFile(path.join(currentDir, "..", "renderer", "index.html"));
};

app.whenReady().then(createWindow);

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void createWindow();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

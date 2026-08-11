import { createWriteStream } from "node:fs";
import { mkdir, stat } from "node:fs/promises";
import https from "node:https";
import path from "node:path";

const version = "43.3.0";
const artifact = `electron-v${version}-win32-x64.zip`;
const url = `https://github.com/electron/electron/releases/download/v${version}/${artifact}`;
const targetDir = path.join(process.env.USERPROFILE, "tools", "electron");
const targetFile = path.join(targetDir, artifact);
const maxAttempts = 8;

await mkdir(targetDir, { recursive: true });

const existingBytes = async () => {
  try {
    return (await stat(targetFile)).size;
  } catch {
    return 0;
  }
};

const request = (target, offset) =>
  new Promise((resolve, reject) => {
    const headers = { "user-agent": "bison-fetch" };
    if (offset > 0) headers.range = `bytes=${offset}-`;

    const req = https.get(target, { headers, timeout: 120000 }, (res) => {
      const location = res.headers.location;
      if (location && res.statusCode >= 300 && res.statusCode < 400) {
        res.resume();
        resolve(request(location, offset));
        return;
      }
      resolve(res);
    });

    req.on("timeout", () => req.destroy(new Error("socket idle for 120s")));
    req.on("error", reject);
  });

const attemptDownload = async () => {
  const offset = await existingBytes();
  const res = await request(url, offset);

  if (res.statusCode === 416) {
    res.resume();
    return true;
  }

  if (res.statusCode !== 200 && res.statusCode !== 206) {
    res.resume();
    throw new Error(`http ${res.statusCode}`);
  }

  const remaining = Number(res.headers["content-length"] ?? 0);
  const total = offset + remaining;
  let received = offset;

  const sink = createWriteStream(targetFile, {
    flags: res.statusCode === 206 ? "a" : "w",
  });

  return new Promise((resolve, reject) => {
    res.on("data", (chunk) => {
      received += chunk.length;
      process.stdout.write(
        `\r${((received / total) * 100).toFixed(1)}%  ${(received / 1048576).toFixed(1)} MB`,
      );
    });
    res.on("error", reject);
    sink.on("error", reject);
    sink.on("finish", () => resolve(received >= total));
    res.pipe(sink);
  });
};

console.log("url    ", url);
console.log("target ", targetFile);

for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
  try {
    const complete = await attemptDownload();
    if (complete) break;
    console.log(`\nincomplete, resuming (attempt ${attempt})`);
  } catch (error) {
    console.log(`\nattempt ${attempt} failed: ${error.message}`);
    if (attempt === maxAttempts) process.exit(1);
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}

const written = await stat(targetFile);
console.log("");
console.log("bytes  ", written.size);

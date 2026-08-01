import { spawn } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const generatedInputs = [
  new URL("../next-env.d.ts", import.meta.url),
  new URL("../tsconfig.json", import.meta.url),
];
const snapshots = await Promise.all(generatedInputs.map((file) => readFile(file)));
const nextCli = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));

let exitCode = 1;
try {
  exitCode = await new Promise((resolve, reject) => {
    const build = spawn(process.execPath, [nextCli, "build"], {
      cwd: fileURLToPath(new URL("..", import.meta.url)),
      env: process.env,
      stdio: "inherit",
    });
    build.once("error", reject);
    build.once("exit", (code) => resolve(code ?? 1));
  });
} finally {
  await Promise.all(generatedInputs.map((file, index) => writeFile(file, snapshots[index])));
}

process.exitCode = exitCode;

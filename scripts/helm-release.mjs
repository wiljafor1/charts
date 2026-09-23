import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile, copyFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { parse, stringify } from "yaml";

const stableVersion = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;

function repository(context) {
  const value = context.env?.GITHUB_REPOSITORY;
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(value ?? "")) {
    throw new Error("GITHUB_REPOSITORY must identify the target GitHub owner/repository");
  }
  return value;
}

export async function verifyConditions(_config, context) {
  repository(context);
  const chart = parse(await readFile(path.join(context.cwd, "standard/Chart.yaml"), "utf8"));
  if (chart.name !== "standard") throw new Error("Release configuration expects the standard chart");
}

export async function prepare(_config, context) {
  const repo = repository(context);
  const version = context.nextRelease.version;
  const tag = context.nextRelease.gitTag;
  if (!stableVersion.test(version) || tag !== `standard-v${version}`) {
    throw new Error("Expected a stable SemVer version and matching standard-vX.Y.Z tag");
  }
  const root = context.cwd;
  const chartPath = path.join(root, "standard/Chart.yaml");
  const chart = parse(await readFile(chartPath, "utf8"));
  if (chart.name !== "standard") throw new Error("Unexpected chart name");
  // Do not set appVersion: each consumer supplies its own image tag/digest.
  chart.version = version;
  await writeFile(chartPath, stringify(chart));

  const releaseDir = path.join(root, ".release");
  const repoDir = path.join(root, ".helm-repository");
  await mkdir(releaseDir, { recursive: true });
  await mkdir(repoDir, { recursive: true });
  const staging = await mkdtemp(path.join(tmpdir(), "helm-release-"));
  try {
    execFileSync("helm", ["package", path.join(root, "standard"), "--destination", staging], { cwd: root, stdio: "pipe" });
    const filename = `standard-${version}.tgz`;
    const archive = await readFile(path.join(staging, filename));
    const checksum = createHash("sha256").update(archive).digest("hex");
    const indexPath = path.join(repoDir, "index.yaml");
    const args = ["repo", "index", staging, "--url", `https://github.com/${repo}/releases/download/${tag}`];
    try {
      await readFile(indexPath);
      args.push("--merge", indexPath);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    execFileSync("helm", args, { cwd: root, stdio: "pipe" });
    const index = parse(await readFile(path.join(staging, "index.yaml"), "utf8"));
    const entry = index.entries?.standard?.find((item) => item.version === version);
    if (!entry || entry.digest !== checksum) throw new Error("Index and chart package checksums differ");

    // Only this run's artifacts may be uploaded, including after a local retry.
    await rm(releaseDir, { recursive: true, force: true });
    await mkdir(releaseDir);
    await copyFile(path.join(staging, filename), path.join(releaseDir, filename));
    await writeFile(path.join(releaseDir, "SHA256SUMS"), `${checksum}  ${filename}\n`);
    await copyFile(path.join(staging, "index.yaml"), indexPath);
    await writeFile(path.join(repoDir, ".nojekyll"), "");
    await writeFile(path.join(repoDir, "index.html"), `<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Helm charts</title>
<h1>Helm charts</h1><p>Add this page's URL with <code>helm repo add</code>.</p>
<p><a href="index.yaml">Helm repository index</a> · <a href="https://github.com/${repo}/releases">Releases and changelog</a></p>
</html>\n`);
    context.logger.log(`Prepared ${filename} and repository index with matching SHA-256`);
  } finally {
    await rm(staging, { recursive: true, force: true });
  }
}

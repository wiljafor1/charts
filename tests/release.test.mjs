import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cp, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { analyzeCommits } from "@semantic-release/commit-analyzer";
import { parse } from "yaml";
import { prepare, verifyConditions } from "../scripts/helm-release.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const logger = { log() {}, error() {} };

for (const [message, expected] of [
  ["fix: correct ingress port", "patch"],
  ["feat: support extra service ports", "minor"],
  ["feat!: rename a required value", "major"],
  ["refactor: change resources\n\nBREAKING CHANGE: old values no longer work", "major"],
  ["docs: clarify installation", null],
  ["chore: update CI tooling", null],
]) {
  test(`Conventional Commit: ${message.split("\n")[0]}`, async () => {
    assert.equal(await analyzeCommits({ preset: "conventionalcommits" }, { cwd: root, commits: [{ hash: "abc1234", message }], logger }), expected);
  });
}

test("packaged Chart version, index and digest agree, while old release URLs are retained", async () => {
  const cwd = await mkdtemp(path.join(tmpdir(), "chart-release-test-"));
  try {
    await cp(path.join(root, "standard"), path.join(cwd, "standard"), { recursive: true });
    const context = { cwd, env: { GITHUB_REPOSITORY: "example/charts" }, logger };
    await verifyConditions({}, context);
    for (const version of ["1.0.0", "1.0.1"]) {
      await prepare({}, { ...context, nextRelease: { version, gitTag: `standard-v${version}` } });
      const archivePath = path.join(cwd, ".release", `standard-${version}.tgz`);
      const chart = parse(execFileSync("helm", ["show", "chart", archivePath], { encoding: "utf8" }));
      assert.equal(chart.version, version);
      assert.equal(chart.appVersion, undefined);
      const index = parse(await readFile(path.join(cwd, ".helm-repository/index.yaml"), "utf8"));
      const entry = index.entries.standard.find((item) => item.version === version);
      const digest = createHash("sha256").update(await readFile(archivePath)).digest("hex");
      assert.equal(entry.digest, digest);
      assert.deepEqual(entry.urls, [`https://github.com/example/charts/releases/download/standard-v${version}/standard-${version}.tgz`]);
      assert.equal(await readFile(path.join(cwd, ".release/SHA256SUMS"), "utf8"), `${digest}  standard-${version}.tgz\n`);
    }
    const index = parse(await readFile(path.join(cwd, ".helm-repository/index.yaml"), "utf8"));
    assert.equal(index.entries.standard.length, 2);
    assert.equal(index.entries.standard.find((item) => item.version === "1.0.0").urls[0], "https://github.com/example/charts/releases/download/standard-v1.0.0/standard-1.0.0.tgz");
  } finally {
    await rm(cwd, { recursive: true, force: true });
  }
});

test("invalid destination or tag fails before packaging", async () => {
  await assert.rejects(verifyConditions({}, { cwd: root, env: {}, logger }), /GITHUB_REPOSITORY/);
  await assert.rejects(prepare({}, { cwd: root, env: { GITHUB_REPOSITORY: "example/charts" }, nextRelease: { version: "1.0.0", gitTag: "wrong-tag" }, logger }), /matching/);
});

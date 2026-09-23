module.exports = {
  branches: ["main"],
  tagFormat: "standard-v${version}",
  plugins: [
    ["@semantic-release/commit-analyzer", { preset: "conventionalcommits" }],
    ["@semantic-release/release-notes-generator", { preset: "conventionalcommits" }],
    ["@semantic-release/changelog", { changelogFile: "standard/CHANGELOG.md" }],
    "./scripts/helm-release.mjs",
    [
      "@semantic-release/git",
      {
        assets: ["standard/Chart.yaml", "standard/CHANGELOG.md", ".helm-repository"],
        message: "chore(release): standard ${nextRelease.version} [skip ci]\n\n${nextRelease.notes}",
      },
    ],
    [
      "@semantic-release/github",
      {
        assets: [
          { path: ".release/*.tgz", label: "Helm chart" },
          { path: ".release/SHA256SUMS", label: "SHA-256 checksums" },
        ],
        successCommentCondition: false,
        failCommentCondition: false,
        releasedLabels: false,
      },
    ],
  ],
};

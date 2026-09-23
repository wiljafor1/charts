# Versionamento e publicação

O workflow [Chart CI and release](../.github/workflows/release.yaml) valida o chart e publica versões automaticamente quando mudanças chegam à branch `main`. Usa semantic-release com Conventional Commits; não é necessário editar a versão nem criar tags manualmente.

## Cálculo da versão

| Commit desde a última release | Resultado |
|---|---|
| `fix: corrigir porta do Service` | Patch: `1.0.0` → `1.0.1` |
| `feat: adicionar uma opção de configuração` | Minor: `1.0.1` → `1.1.0` |
| `feat!: renomear um value obrigatório` | Major: `1.1.0` → `2.0.0` |
| Footer `BREAKING CHANGE: ...` | Major |
| Apenas `docs:`, `test:`, `ci:` ou `chore:` | Sem release |

Se houver vários commits, prevalece o maior incremento. `perf:` também gera patch. Em squash merge, use o formato no título do PR/commit resultante; os títulos dos commits descartados não entram no histórico da `main`.

A primeira publicação automática, sem tags anteriores, é **1.0.0**, conforme o padrão do semantic-release. O pacote local 0.1.0 foi uma preparação sem release publicada. Depois disso, as tags `standard-vX.Y.Z` são a referência para o próximo incremento.

A automação atualmente trata um chart, `standard`. Mudanças `feat`/`fix` no repositório inteiro participam do cálculo. Para novos charts com ciclos independentes, separar a configuração de release por chart.

## Fluxo

1. PRs e pushes para `main` executam lint, testes de templates e testes da automação.
2. Após os testes, somente pushes/execuções manuais na `main` podem publicar.
3. O semantic-release calcula a versão, atualiza `standard/Chart.yaml` e gera `standard/CHANGELOG.md`.
4. O plugin local empacota o chart, calcula SHA-256 e atualiza `.helm-repository/index.yaml`, preservando as URLs das versões anteriores.
5. O bot faz commit dos metadados de release, cria a tag e publica o `.tgz` e `SHA256SUMS` na GitHub Release.
6. O mesmo workflow publica o índice no GitHub Pages.

A versão da imagem de cada aplicação continua nos seus values. `appVersion` não é preenchido com a versão do chart.

O conteúdo de `.helm-repository` é gerado e versionado pela automação. Pacotes e arquivos temporários ficam em `.release/`, ignorado pelo Git. Os `.tgz` publicados são assets de Releases, não arquivos binários na branch principal.

## Configuração do GitHub

Para reutilizar em outro repositório público:

- Configure o remote e a branch `main`.
- Habilite GitHub Actions e GitHub Pages com **Source: GitHub Actions**.
- O workflow usa apenas o `GITHUB_TOKEN` fornecido pelo GitHub, sem PAT ou credencial do cluster. O job de publicação solicita `contents: write`, `pages: write` e `id-token: write`; PRs executam somente testes com acesso de leitura.
- O bot precisa poder gravar os metadados de release na `main`. Se houver regras que exijam PR para todas as alterações, adapte para releases via PR; não desabilite proteções existentes para contornar o erro.
- O environment `github-pages` deve permitir a branch `main`. Se configurar aprovadores no environment, a publicação passa a depender dessa aprovação.

O destino das Releases é obtido de `GITHUB_REPOSITORY`, sem owner/domínio fixado no chart ou nos scripts. Este modelo usa índice público e assets públicos de Releases; para distribuição privada, prefira um registry OCI com autenticação adequada.

## Consumo

No repositório configurado:

```bash
helm repo add application-charts https://wiljafor1.github.io/charts
helm repo update
helm search repo application-charts/standard --versions

helm upgrade --install minha-api application-charts/standard \
  --version 1.0.0 \
  --namespace apps --create-namespace \
  -f values-minha-api.yaml \
  --wait --timeout 5m
```

No Rancher, cadastre essa mesma URL em **Apps → Repositories**. Fixe a versão consumida por cada aplicação e revise o changelog antes de atualizar versões major.

## Falhas e reexecução

- Um teste com falha impede a publicação.
- Sem commits publicáveis, não é criada uma nova versão.
- Falha somente no deploy do Pages: reexecute o workflow pela opção **Run workflow**, na `main`; o índice versionado permite tentar novamente sem criar outra versão.
- Falha depois da criação da tag, mas antes do upload completo dos assets: verifique a Release e os logs. O semantic-release pode considerar a tag já publicada; não apague/reutilize uma versão já consumida. Complete os assets da mesma release a partir do commit/tag correspondente ou publique uma correção com nova versão, conforme o que já ficou disponível.
- Se novos commits chegarem enquanto uma release está sendo preparada, o workflow não força push sobre eles. Uma execução seguinte usa o histórico atualizado.

## Verificação local

```bash
# Node.js 24.10+ e Helm no PATH.
npm ci --ignore-scripts
npm test
make check PYTHON=.venv/bin/python
```

Os testes da automação usam repositórios/diretórios temporários, verificam SemVer, metadados do pacote, checksums e preservação do índice anterior; não publicam nada.

Referências: [semantic-release](https://github.com/semantic-release/semantic-release), [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) e [deploy-pages](https://github.com/actions/deploy-pages).

# Application charts

Charts Helm reutilizáveis para aplicações Kubernetes, sem dependência de domínio, organização, registry ou distribuição específica.

## Standard

O chart [`standard`](standard/README.md) instala uma aplicação por release, usando Deployment. Atende APIs HTTP e workers, com requests/limits explícitos, probes configuráveis e integrações opcionais.

| Padrão por réplica | Valor |
|---|---|
| CPU request / limit | `100m` / `500m` |
| Memória request / limit | `128Mi` / `256Mi` |
| Armazenamento efêmero request / limit | `64Mi` / `512Mi` |
| Réplicas | `1` |
| Exposição | Service `ClusterIP`; Ingress desabilitado |
| Rollout | Sem pod extra; uma réplica pode ficar indisponível durante o upgrade |

Imagem e tag/digest são obrigatórios; não há imagem de demonstração instalada implicitamente. O orçamento é um ponto de partida para aplicações pequenas e precisa ser ajustado ao consumo de cada aplicação.

```bash
# Use um arquivo próprio, com imagem, configuração e Secrets da sua aplicação.
helm upgrade --install minha-api ./standard \
  --namespace apps --create-namespace \
  -f /caminho/values-minha-api.yaml \
  --wait --timeout 5m
```

Consulte o [guia do chart](standard/README.md) para os values mínimos, HTTPS, Secrets, persistência, observabilidade e uso como dependência de outro chart.

## Exemplos

Os arquivos em [`examples/`](examples/) usam imagens e domínios fictícios. Adapte-os antes de instalar.

| Arquivo | Uso |
|---|---|
| [api.values.yaml](examples/api.values.yaml) | API, health checks HTTP, ConfigMap e referência a Secret existente |
| [traefik-tls.values.yaml](examples/traefik-tls.values.yaml) | Overlay de HTTPS com Traefik e Secret TLS existente |
| [worker.values.yaml](examples/worker.values.yaml) | Worker sem Service nem probes de rede |
| [monitoring.values.yaml](examples/monitoring.values.yaml) | Overlay de ServiceMonitor para `/metrics` |
| [autoscaling.values.yaml](examples/autoscaling.values.yaml) | Overlay de HPA, PDB e rollout com capacidade adicional |
| [persistence.values.yaml](examples/persistence.values.yaml) | Overlay de PVC para uma réplica |

Não combinar o overlay de HPA com um PVC de escrita única. O chart rejeita essa combinação antes de instalar.

## Verificação e pacote

Requisitos: Helm 3 ou 4, Python 3.10+ e PyYAML para os testes. Os comandos de verificação não instalam recursos no cluster.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r tests/requirements.txt
make check PYTHON=.venv/bin/python
make package
```

O pacote local é gerado em `dist/standard-<versão>.tgz`.

## Publicação automática

Pushes para `main` passam pelo CI e publicam versões no GitHub Releases e um repositório Helm no GitHub Pages. Conventional Commits definem o incremento: `fix:` → patch, `feat:` → minor, `feat!:` / `BREAKING CHANGE:` → major. Não edite a versão manualmente.

O workflow mantém `Chart.yaml`, changelog, tag, pacote e índice sincronizados. Consulte [versionamento, configuração e consumo](docs/releases.md).

```bash
helm repo add application-charts https://wiljafor1.github.io/charts
helm repo update
helm search repo application-charts/standard --versions
```

# standard

Chart Helm genérico para uma aplicação com um container principal por release. Usa Deployment e APIs Kubernetes estáveis a partir de 1.25. Não depende de uma distribuição, domínio, organização, StorageClass ou registry específico.

A configuração completa e comentada está em [values.yaml](values.yaml). O [schema](values.schema.json) valida tipos, chaves desconhecidas nas opções do chart, recursos obrigatórios, probes e combinações inválidas. Campos que representam estruturas nativas extensíveis do Kubernetes, como `affinity`, são validados pela API Kubernetes.

## Instalação mínima

Crie um arquivo por aplicação, fora dos values base:

```yaml
# values-minha-api.yaml: substitua pela imagem real da aplicação.
image:
  repository: registry.example.com/team/api
  tag: "1.0.0"
containerPort: 8080
```

A imagem deve executar com usuário não root e UID numérico configurado na imagem, ou com `podSecurityContext.runAsUser` definido nos values. O filesystem raiz é somente leitura; `/tmp` tem um volume gravável de até 64Mi. Configure volumes adicionais para outros diretórios que a aplicação escreve.

```bash
helm upgrade --install minha-api ./standard \
  --namespace apps --create-namespace \
  -f values-minha-api.yaml \
  --wait --timeout 5m
```

`image.repository` e uma `image.tag` ou `image.digest` são obrigatórios. Um digest `sha256:...` prevalece sobre a tag. A versão do chart não é usada como versão da imagem. Para registries privados, configure `imagePullSecrets: [{name: registry-credentials}]` com um Secret existente no namespace.

Para inspecionar antes de instalar:

```bash
helm lint ./standard --strict -f values-minha-api.yaml
helm template minha-api ./standard -n apps -f values-minha-api.yaml
# Requer namespace existente e acesso à API; não persiste os recursos.
helm template minha-api ./standard -n apps -f values-minha-api.yaml \
  | kubectl apply --dry-run=server --validate=strict -f -
```

Rodar `helm lint ./standard` sem fornecer imagem falha intencionalmente. Para testar o chart sem uma imagem real, use os values de exemplo; lint e template não baixam a imagem.

## Recursos e disponibilidade

| Recurso por réplica | Request | Limit |
|---|---|---|
| CPU | 100m | 500m |
| Memória | 128Mi | 256Mi |
| Armazenamento efêmero | 64Mi | 512Mi |

São valores iniciais para aplicações pequenas. Meça inicialização, tráfego e tarefas de background antes de usar em produção. JVMs, builds ou processamento pesado podem precisar de mais memória. CPU limitada pode sofrer throttling; exceder o limit de memória pode encerrar o container por OOM. Armazenamento efêmero inclui logs, camada gravável e `emptyDir` em disco; seu limit é tratado pelo kubelet via eviction, não como quota de filesystem em tempo real.

O padrão é uma réplica, `maxSurge: 0` e `maxUnavailable: 1`. Evita um pod adicional no rollout, mas permite indisponibilidade durante a troca. Quando houver capacidade, duas réplicas e `maxSurge: 1` / `maxUnavailable: 0` reduzem esse impacto. Réplicas não são distribuídas automaticamente entre máquinas; use `affinity` ou `topologySpreadConstraints` conforme o ambiente.

Requests/limits de CPU e memória devem permanecer explícitos. O chart não altera reservas dos nodes, LimitRanges ou ResourceQuotas dos namespaces. A soma dos limites das aplicações pode superar a capacidade física; planeje também réplicas máximas e picos de rollout.

## Configuração, Secrets e identidade

- `env` e `envFrom` aceitam a estrutura nativa Kubernetes, incluindo `secretKeyRef`, `configMapRef`, `fieldRef` e `secretRef`.
- `configMap.enabled: true` cria `<fullname>-config`. `configMap.data` deve conter strings. Por padrão, as chaves são injetadas como variáveis de ambiente; use nomes válidos para essa finalidade.
- Para arquivos de configuração, use `configMap.envFrom: false` e monte o ConfigMap com `extraVolumes` / `extraVolumeMounts`. `fullnameOverride` permite fixar o nome; o sufixo `-config` é preservado mesmo em nomes longos.
- Uma alteração no ConfigMap criado pelo chart atualiza um checksum no pod e provoca rollout. Mudanças em ConfigMaps/Secrets externos exigem rollout ou um mecanismo externo de reload.
- O chart não cria Secrets com senhas ou certificados em values. Referencie Secrets existentes no mesmo namespace.
- Uma ServiceAccount própria é criada por padrão, sem montagem automática do token da API. Para reutilizar uma identidade, use `serviceAccount.create: false` e `serviceAccount.name`. Não são criados Role/ClusterRole/Bindings.

Os labels de seleção são protegidos contra sobrescrita por labels adicionais. Evite alterar `nameOverride` ou `fullnameOverride` depois da instalação: isso pode mudar nomes ou seletores imutáveis.

## Probes e workers

Startup e readiness usam TCP na porta `http` por padrão, verificando que a aplicação aceita conexões. Liveness fica desabilitada até ser configurada para a aplicação. TCP não garante a saúde funcional da aplicação.

Para usar endpoints HTTP, selecione o handler com `type`:

```yaml
startupProbe:
  type: httpGet
  httpGet:
    path: /healthz
    port: http
readinessProbe:
  type: httpGet
  httpGet:
    path: /readyz
    port: http
livenessProbe:
  enabled: true
  type: httpGet
  httpGet:
    path: /healthz
    port: http
```

`type` aceita `httpGet`, `tcpSocket`, `exec` ou `grpc`; configure a estrutura de mesmo nome. Apenas o handler selecionado é renderizado, evitando colisões ao combinar arquivos de values. Startup usa 30 tentativas de 5 segundos; enquanto não passar, o Kubernetes aguarda antes de executar readiness/liveness. Ajuste para a duração real do boot. Evite usar dependências externas transitórias como motivo de reinício pela liveness.

Para um worker sem HTTP, desabilite `service`, `startupProbe` e `readinessProbe`; configure probes `exec` se o processo fornecer health checks. A porta declarada no container não cria um servidor nem expõe o worker. Veja [worker.values.yaml](../examples/worker.values.yaml).

## Service e HTTPS

O Service padrão é `ClusterIP`, porta 80 → porta nomeada `http` do container, cujo valor padrão é 8080. `service.extraPorts` expõe portas adicionais; use um `targetPort` numérico para listeners extras ou `http` para a porta principal. Declarar uma porta no Service não faz a aplicação escutar nela.

O Ingress usa `networking.k8s.io/v1`, sem CRDs do controlador. `ingress.className` vazio usa a seleção padrão do cluster. O [overlay Traefik](../examples/traefik-tls.values.yaml) configura explicitamente `traefik`, `websecure` e um Secret TLS existente:

```bash
helm upgrade --install minha-api ./standard -n apps --create-namespace \
  -f values-minha-api.yaml \
  -f examples/traefik-tls.values.yaml \
  --wait --timeout 5m
```

Substitua `app.example.com` e `app-tls` pelos valores da aplicação. O Secret deve conter `tls.crt` e `tls.key`, ser do tipo `kubernetes.io/tls` e existir no namespace da aplicação. DNS e emissão/renovação do certificado são gerenciados separadamente. É possível usar anotações de cert-manager com um Issuer apropriado em vez de gerenciar o certificado manualmente.

Neste modelo, um balanceador na frente pode encaminhar TCP/443 até o ingress controller. O controlador termina o TLS e encaminha HTTP para o Service da aplicação. Não é necessário que a aplicação termine TLS. Passthrough até a aplicação exigiria uma rota TCP específica do controlador e não é implementado por este chart.

O overlay expõe o endpoint HTTPS; não cria redirecionamento HTTP→HTTPS nem configura entrypoints do controlador.

## HPA e PDB

HPA usa `autoscaling/v2`, depende de Metrics Server e fica desabilitado por padrão. CPU e/ou memória são comparadas com os requests. Defina `targetCPUUtilizationPercentage: null` para desabilitar a métrica de CPU e configurar somente memória; é necessário manter ao menos uma métrica.

Quando HPA está habilitado, `Deployment.spec.replicas` é omitido para não disputar o campo com o autoscaler. `replicaCount` passa a ser ignorado. Planeje capacidade para `maxReplicas`, rollout e requisitos de distribuição. HPA não adiciona capacidade às máquinas.

PDB também é opcional e trata interrupções voluntárias, como drain; não protege contra falha física de node e não limita diretamente os rollouts do Deployment. Configure apenas `minAvailable` ou `maxUnavailable`. Para usar `minAvailable`, defina `maxUnavailable: null`. Um PDB que exige uma réplica disponível quando existe apenas uma pode bloquear manutenção.

O [overlay autoscaling](../examples/autoscaling.values.yaml) usa 2–3 réplicas, surge de uma réplica e PDB. Ele exige mais capacidade que os defaults.

## Persistência

Desabilitada por padrão. Ao habilitar:

- `existingClaim` vazio cria um PVC; preenchido reutiliza um PVC existente.
- `storageClass: ""` omite o campo e usa a classe padrão; `"-"` emite `storageClassName: ""`; um nome explícito seleciona a classe.
- `ReadWriteOnce` e `ReadWriteOncePod` são tratados conservadoramente como escrita única: exigem uma réplica, HPA desabilitado e estratégia `Recreate`. RWO permite múltiplos pods no mesmo node, mas este chart evita depender dessa colocação durante upgrades.
- `ReadWriteMany` permite múltiplas réplicas apenas se o driver e a aplicação suportarem acesso compartilhado. Para PVC externo, `accessModes` deve refletir o acesso realmente oferecido pelo volume.
- O chart monta o volume em `/data` por padrão. Ajuste `fsGroup`/UID e permissões para o processo não root; não há init container privilegiado para executar chown.
- `retain: true` adiciona `helm.sh/resource-policy: keep` ao PVC criado. Ele fica após uninstall e precisa de gerenciamento/remoção manual. Isso não substitui backups nem a política de reclaim do PV. Verifique o PVC retido antes de reinstalar a mesma release; considere reutilizá-lo via `existingClaim`.

O chart não cria StatefulSet nem replicas de banco de dados. Bancos e sistemas com identidade/ordenação específicas devem usar charts próprios.

## Métricas

`serviceMonitor.enabled: true` cria um `ServiceMonitor`. É necessário ter a CRD do Prometheus Operator instalada e um Prometheus que selecione o namespace e os labels do monitor.

O padrão coleta `/metrics`, na porta nomeada `http`, a cada 60 segundos, com timeout de 10 segundos. A aplicação precisa expor métricas Prometheus nesse caminho. Para porta dedicada, adicione-a em `service.extraPorts` e use o mesmo nome em `serviceMonitor.port`. Configure `serviceMonitor.labels` conforme o seletor do Prometheus.

As métricas Kubernetes de CPU, memória, requests e limits vêm de kube-state-metrics/kubelet na stack de monitoring e não dependem do ServiceMonitor da aplicação.

## Uso como dependência

É possível instalar o chart diretamente com values por app ou incluí-lo em um chart específico. Para desenvolvimento local, no `Chart.yaml` do chart consumidor:

```yaml
apiVersion: v2
name: minha-api
version: 0.1.0
dependencies:
  - name: standard
    version: 1.0.0
    repository: file:///caminho/para/charts/standard
```

Nos values do consumidor, coloque as configurações dentro da chave `standard`:

```yaml
standard:
  image:
    repository: registry.example.com/team/api
    tag: "1.0.0"
```

Execute `helm dependency update` no chart consumidor. Para distribuição, empacote e publique em um repositório Helm ou registry OCI escolhido, substituindo a referência local. Não há destino de publicação embutido.

A publicação deste repositório é automatizada via Conventional Commits. Consulte [releases](../docs/releases.md) e escolha uma versão publicada ao declarar a dependência.

## Validação

`make check` na raiz executa lint estrito com exemplos e testes de renderização. Os testes verificam seletores, roteamento para Services, referências a volumes/Secrets, ownership de réplicas pelo HPA, orçamento padrão e rejeição de configurações incompatíveis.

Durante a preparação, os manifests de API com HTTPS, HPA, PDB, ConfigMap e ServiceMonitor, além de uma configuração separada com PVC, foram aceitos em dry-run por uma API Kubernetes 1.36.4. Isso valida os objetos, não o funcionamento de uma imagem real, DNS, endpoints HTTP ou conteúdo dos Secrets. Nenhuma aplicação foi instalada.

Referências: [formato e schema de charts Helm](https://helm.sh/docs/topics/charts/), [probes Kubernetes](https://kubernetes.io/docs/concepts/workloads/pods/probes/), [HPA](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/), [Ingress Traefik](https://doc.traefik.io/traefik/reference/routing-configuration/kubernetes/ingress/) e [API do Prometheus Operator](https://prometheus-operator.dev/docs/api-reference/api/).

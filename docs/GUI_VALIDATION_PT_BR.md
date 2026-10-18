# Ensaio gráfico do Claude original com o Claude Duo

Este roteiro prepara a etapa de viabilidade do [roadmap](ROADMAP_PT_BR.md).
O código de manutenção foi testado com dados inventados. **Login, contas
simultâneas e Code na cópia continuam sem validação gráfica.** Uma assinatura
local válida ou um ícone diferente não comprova independência das contas.

**Estado em 17/10/2026:** a preparação real foi concluída e o usuário abriu o
Duo. O app solicitou acesso à entrada preexistente `Claude Safe Storage`; o
usuário negou. G01/G11 ficaram inconclusivos e o login está pausado. Ver o
[relato do bloqueio e critérios de retomada](KEYCHAIN_FIRST_LAUNCH_PT_BR.md) e
o [registro sanitizado](evidence/gui-first-launch.json). Os demais casos ainda
não foram executados.

A seleção de destino privado passou por oito novos testes, dentro da suíte de
145 casos, e por oito checagens de construção/assinatura/conteúdo com a origem
real, em pasta descartável. Nos últimos, processos foram simulados e não houve
abertura do Claude. [Evidências e hashes](evidence/gui-preparation.json).

## Ambiente escolhido

Usar **a sessão habitual do usuário no macOS**, conforme sua decisão. Não criar
outro usuário local. O original conserva o perfil padrão existente; o Duo
começa com pastas novas e projetos inventados. Os testes de código continuam
em pastas descartáveis, sem exigir login nem alteração de perfis reais.

O teste gráfico do original envolverá seu perfil real. Pastas novas do Duo
reduzem mistura de dados, mas não isolam o Chaveiro, todos os locais globais de
configuração ou arquivos acessíveis ao mesmo UID. Independência de autenticação
continua sendo algo a demonstrar. Não trocar HOME nem copiar credenciais para
simular separação de contas. A preparação abaixo foi executada com uma
configuração nova; não converteu os perfis legados. Personal e Trabalho foram
movidos para a Lixeira a pedido do usuário, preservando seus dados.

## Preparação e participação do usuário

1. Inventariar caminhos, identificadores, atalhos e configuração da instalação
   existente, sem coletar conteúdo de conta. A cópia legada Personal pode usar
   o mesmo perfil padrão do original; não abrir os dois simultaneamente.
   Conferir também manutenção legada que possa operar durante o ensaio.
2. Confirmar o usuário efetivo e seu home. Todas as operações usam essa sessão
   real, sem `sudo`, sem trocar HOME e sem macros nativas de teste.
3. Conferir o pacote revisado e seu manifesto com a referência independente do
   candidato. Instalar o conjunto completo pelo
   [instalador versionado](TOOLSET_INSTALLATION.md), preservando `~/bin`,
   configuração e atalhos legados até uma transição revisada.
4. Selecionar o destino privado `~/Applications`, que precisa ser físico,
   próprio e ter modo 0700. Se ausente, criar a pasta; se existente e incompatível,
   revisar o destino sem alterar permissões de outros apps para prosseguir.
   `@apps user` apenas valida a pasta, recusando links, permissões especiais e ACLs
   de concessão; não a cria nem muda seu modo.
5. Criar uma configuração de ensaio separada da configuração em uso, com o modo
   original + cópia e uma única cópia Duo. Exigir destino de app e pastas
   Desktop/Code novos; se já contiverem dados, revisar sem sobrescrever ou
   apagar. Não importar o perfil padrão inteiro, tokens ou Chaveiro.
6. Coordenar o fechamento dos apps para a construção, sem encerrar tarefas
   silenciosamente. Usar apenas a configuração e a manutenção escolhidas para
   o candidato, sem um LaunchAgent novo nem manutenção legada concorrente.
7. Conferir a origem oficial, construir o Duo e verificar conteúdo, configuração
   e assinatura antes de abrir. Não substituir erros de observação de processos
   por resultados simulados. Abrir o original somente após conferir o conflito
   com a cópia Personal e os destinos dos atalhos.

Essa preparação é feita uma vez pelo responsável técnico. O ensaio e o uso
diário são na interface do Claude; não exigem usar o Claude Code CLI.
O ensaio e o uso diário pretendido ocorrem na mesma sessão habitual. Isso não
converte automaticamente a instalação legada nem comprova que os aplicativos
modificados sejam compatíveis com suas contas.

## Topologia do laboratório

| Item | Local na sessão habitual |
|---|---|
| Original, executável oficial | `/Applications/Claude.app`, somente origem/leitura pelas nossas ferramentas |
| Duo | `~/Applications/Claude Duo.app` |
| Dados Desktop do original | `~/Library/Application Support/Claude`, perfil real existente |
| Configuração Code do original | `~/.claude` e outros locais efetivos, preservando dados existentes |
| Dados Desktop do Duo | `~/Library/Application Support/Claude-Duo` |
| Configuração Code solicitada ao Duo | `~/.claude-duo` via `CLAUDE_CONFIG_DIR` |
| Projetos inventados e distintos | `~/Claude Duo Lab/original` e `~/Claude Duo Lab/duo` |

Exemplo de configuração separada para uma cópia nova de ensaio, após revisar
os destinos; não substituir a configuração legada por este exemplo:

```text
@mode original-copy
@apps user
Duo | com.guibrbs.claude-duo.lab | ~/Library/Application Support/Claude-Duo | 212 | CLAUDE_CONFIG_DIR=~/.claude-duo
```

O identificador `.lab` identifica o candidato de teste; não migra o identificador
de uma cópia instalada. Mudar identidade, localização ou versão depois do teste
exige nova validação do que a mudança afetar. O original permanece fora da lista
de destinos. A seleção de pasta não altera a origem `/Applications/Claude.app`.

O bloqueio de manutenção é comum a rebuild, caches e checkpoints **dentro da
pasta de aplicativos selecionada**. Não coordenamos duas configurações que
escolham pastas distintas e reutilizem os mesmos perfis. Usar somente a
configuração do laboratório, sem cópias antigas sobre esses dados. Trocar
`@apps` não migra nem desativa apps antigos e altera a vinculação de integridade.

## Conferência antes da abertura

Registrar versão e build do macOS, arquitetura, versão do Claude, commit/hash do
pacote, identificador e caminho exato do Duo. Conferir assinatura Anthropic e
Gatekeeper da origem, assinatura/conteúdo da cópia e destinos dos iniciadores.
Registrar hashes dos arquivos críticos da origem antes/depois da construção.
Esses testes não devem ler conteúdo de perfis, variáveis de processos ou Chaveiro.

Abrir o original pelo caminho completo e o Duo pelo seu caminho privado no
Finder. Conferir atalhos/Dock antes de adicioná-los. Não abrir um app retido
em uma transação nem procurar uma cópia só pelo nome. Retornos pelo navegador
devem ser observados; o iniciador atual recusa argumentos e URLs.

O app oficial é compartilhado no disco: uma atualização por outro processo pode
alterá-lo. Se origem, versão ou assinatura mudarem durante o ensaio, pausar e
identificar um novo candidato. Não conceder privilégios de administrador,
desativar Gatekeeper ou contornar políticas de organização para obter um passe.

## Matriz de aceitação

Fluxo declarado pelo usuário: **login por link de e-mail, sem SSO**. G07 é
obrigatório para esse link; SSO fica fora do escopo inicial e não será tratado
como testado.

Na abertura da matriz, todos os itens começam como **NÃO EXECUTADO**; os
resultados efetivos ficam no registro datado acima. Usar somente os rótulos A e B
no relatório público; confirmar e-mail/organização privadamente na interface.
Declarar os recursos necessários. Nova autenticação é feita pelo usuário dentro
do Claude/navegador. Saída da conta A, reinício e encerramento da sessão macOS
são combinados com o usuário; o ensaio não os força sobre trabalho em andamento.
O cenário de um original com perfil vazio não foi ensaiado nessa escolha de
ambiente. Registrar a cobertura obtida sem usar o perfil real como descartável.

| ID | Ensaio | Evidência necessária |
|---|---|---|
| G01 | Entrar em A no original e B no Duo | Identidade esperada na interface de cada app |
| G02 | Inverter a ordem de abertura e, quando o usuário fizer a reautenticação, de login | Não trocar a conta do outro app; não apagar o perfil original para obter dados novos |
| G03 | Abrir Code local nos dois simultaneamente | Conta efetiva do Code confirmada; tarefas nos projetos corretos |
| G04 | Fechar, reabrir, sair da sessão macOS e reiniciar | Retomada e identidades preservadas, sem abrir versões retidas |
| G05 | Sair e entrar novamente em B com A ativo | Sessão/tarefa de A continua correta |
| G06 | Renovação de login e revogação da sessão de teste em B | Impacto observado; não revogar sessões habituais ou todas as sessões da conta |
| G07 | Retorno do link de e-mail/navegador | Retorno para a conta e janela corretas; sem burlar o iniciador |
| G08 | Finder, Dock e atalhos | Caminhos, identidade do app e perfil corretos |
| G09 | Construção e checkpoint com original, Duo ou ambos abertos | Recusa segura, sem encerrar tarefas para forçar manutenção |
| G10 | Preferências e extensões inventadas | Reaproveitamento sem transferir autenticação, conforme proposta abaixo |
| G11 | Permissões e recursos declarados | Funcionamento por identidade; falhas registradas |

Antes de G01, observar pedidos de acesso ao Chaveiro. Um pedido inesperado à
entrada do original bloqueia o login até revisão. Negar o pedido; não apagar
entradas nem liberar acesso para forçar o teste. O candidato atual encontrou
esse bloqueio. Pasta, identificador ou ícone distintos não o resolvem por si.

Criar marcadores inofensivos distintos nos projetos e nas instruções de teste.
Uma resposta contendo um marcador demonstra configuração carregada, não prova
qual conta pagou/executou o Code. Não usar essa resposta como substituto da
identificação efetiva da conta; se não for possível observá-la, marcar
**INCONCLUSIVO**, mantendo o requisito de viabilidade aberto.

A [proposta de reaproveitamento](PROFILE_REUSE_PT_BR.md) adiciona o requisito do
usuário sem compartilhar o perfil inteiro. Primeiro validar autenticação básica;
depois repetir os casos essenciais com configurações inventadas importadas. O
importador ainda não está implementado, portanto G10 continua pendente.
Se o serviço não permitir limitar uma revogação à sessão de ensaio, manter
esse caso pendente sem revogar sessões habituais. Não usar a limpeza
de caches como teste de recusa sem saída: o comando atual pode pedir ao app
selecionado que feche antes da limpeza, comportamento distinto de construção
e checkpoint.

## Registro e encerramento

Para cada caso registrar data, candidato, tipo de conta A/B, resultado
(`APROVADO`, `FALHOU`, `INCONCLUSIVO`, `NÃO EXECUTADO` ou `NÃO APLICÁVEL`) e
observação sanitizada. A exclusão de um recurso do escopo exige decisão explícita;
não transformar um teste pendente em aprovado. Não publicar perfis, logs de
autenticação, conversas, URLs de callback ou capturas contendo dados privados.

Troca inesperada de conta, perda de dados ou origem incerta interrompe a
liberação. No fim, fechar apps e preservar resultados sanitizados. Encerrar
sessões do Duo ou remover suas pastas de ensaio são ações posteriores, com
revisão; preservar a conta local, o perfil real e os dados legados. Não apagar
perfis automaticamente ou presumir que excluir arquivos revoga sessões no
serviço. Nenhum resultado autoriza substituir os perfis reais ou iniciar
atualização automática antes dos demais critérios do roadmap.

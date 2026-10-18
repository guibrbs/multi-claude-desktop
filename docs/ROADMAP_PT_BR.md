# Roadmap para usar duas contas no Claude Desktop e no Code

Plano atualizado em 17/10/2026, no
[PR #1 do seu fork](https://github.com/guibrbs/multi-claude-desktop/pull/1), ainda
em rascunho. A base anterior `2d37bf6` possui as evidências históricas citadas
abaixo. O instalador e a política de perfis agora têm testes adicionais; a
preparação real foi concluída. O primeiro Duo aberto pelo usuário pediu acesso
à entrada preexistente `Claude Safe Storage`, e o usuário negou. O ensaio de
contas está bloqueado: [achado KC01](KEYCHAIN_FIRST_LAUNCH_PT_BR.md). O documento
distingue testes descartáveis, preparação real e validação de contas pendente.
Os [experimentos posteriores](KEYCHAIN_NAMESPACE_EXPERIMENTS_PT_BR.md) encontraram
um caminho para uma entrada com nome próprio, sem mudar a tela de login do
Desktop. O construtor de produção já aplica essa troca ao Duo, com verificação
regenerada da origem; o Duo instalado ainda não foi reconstruído e as contas
não foram testadas. O bloqueio de liberação permanece.

## Resultado que queremos

Você usa **o Claude original e uma cópia**, ambos com a interface do próprio
Claude Desktop. A cópia se chama **Claude Duo**. Você executa tarefas no Code com a conta correspondente. Por
exemplo, o original atende à conta pessoal e a cópia à conta de trabalho; a
escolha das contas pode ser invertida. O uso diário deve ser gráfico. Cada
perfil tem pastas próprias, e instalação e atualização devem reconhecer falhas
e preservar dados.

O original mantém a identidade e o atualizador oficiais. A implementação atual
permite criar cópias modificadas com nomes, identificadores e iniciadores
próprios. Cada cópia troca a assinatura externa por uma assinatura local;
a identidade e as permissões exclusivas da Anthropic permanecem uma limitação
nessa cópia. A separação completa de autenticação entre original e cópia ainda
precisa ser demonstrada na interface. Esta preferência substitui o desenho de
duas cópias para o uso diário. Personal e Trabalho foram movidos para a Lixeira
a pedido do usuário; seus dados e a configuração legada foram preservados.

## Topologia preferida e atualização da cópia

| Aplicativo | Papel | Dados |
|---|---|---|
| `/Applications/Claude.app` | Uso diário de uma conta; recebe a atualização oficial | Perfil Desktop padrão e configuração Code padrão |
| `/Applications/Claude Duo.app` | Uso diário da segunda conta; reconstruído pelas nossas ferramentas | Pastas Desktop e Code exclusivas da cópia |

Nesse modo, reservar os diretórios padrão ao original. A configuração gerenciada
deve listar somente a cópia; configurar o original como destino de reconstrução
continua proibido. A política explícita `@mode original-copy` já reserva os dois
perfis padrão e exige uma única cópia. Configurações sem cabeçalho preservam o
fluxo legado, em que uma cópia Pessoal pode usar o padrão. Essa cópia legada e
o original não devem usar esse perfil simultaneamente. Nenhuma configuração em
uso foi convertida automaticamente.

O fluxo de atualização pretendido é:

1. O Claude original recebe sua atualização oficial normalmente.
2. Um observador detecta mudança da origem e identifica que a cópia precisa
   ser reconstruída. Comparar só números de versão não comprova a origem nem
   detecta todas as alterações de conteúdo.
3. Aguardar o original e a cópia fecharem e confirmar uma origem verificável
   e estável. Não encerrar tarefas automaticamente.
4. Construir uma nova cópia em staging privado a partir do original atualizado,
   aplicar somente as mudanças previstas e verificar assinatura e conteúdo.
   Recusar mudanças da origem ou observações incertas durante a operação.
5. Publicar a cópia pronta por troca atômica, preservando a anterior. Os dados
   e a configuração da segunda conta ficam fora do bundle e não são copiados
   do perfil do original.
6. Informar sucesso ou falha. Abertura da nova versão e eventual migração dos
   seus dados seguem os testes de compatibilidade; manter o bundle anterior
   não comprova que um downgrade seja compatível.

Hoje o watchdog verifica e notifica; **a reconstrução automática ainda não está
implementada**. O construtor já prepara, verifica e publica cópias, e exige que
os aplicativos Desktop observados estejam fechados. O trabalho adicional é
orquestrar detecção, espera, seleção da única cópia, reconstrução e comunicação
de falhas. A atualização do original não modifica os arquivos da cópia por si.

O modelo preserva a identidade oficial no aplicativo usado pela primeira
conta e reduz a quantidade de bundles modificados. A cópia continua sujeita às
limitações de assinatura e autenticação já documentadas.

Sua prioridade continua sendo **segurança primeiro**. O protótipo de um novo
gerenciador nativo está adiado. O caminho atual deve passar pelos testes antes
de investirmos em outra interface.

O usuário decidiu **não criar outro usuário no macOS**. O ensaio gráfico será
na sessão habitual, com pastas novas para o Duo e o perfil existente do original.
O [roteiro atualizado](GUI_VALIDATION_PT_BR.md) começa pela revisão de cópias e
atalhos legados para evitar acesso simultâneo ao mesmo perfil padrão. Novas
pastas não constituem isolamento do Chaveiro ou de arquivos do mesmo UID.

Requisito adicional: reaproveitar no Duo as preferências, MCPs e plugins do
original, pois a pessoa é a mesma. A [proposta de importação seletiva](PROFILE_REUSE_PT_BR.md)
define o original como referência, preserva ajustes próprios do Duo e mantém
login, sessões e credenciais separados. Importador e sincronização ainda não
estão implementados. Isso não significa copiar todo o perfil ou compartilhar
as pastas das duas contas.

## Onde estamos

| Item | Situação comprovada | Limite da evidência |
|---|---|---|
| Configurações e pastas | Validações de conteúdo, caminhos, permissões e separação de pastas implementadas | Pastas distintas não isolam programas executados pelo mesmo usuário do macOS |
| Construção das cópias | Origem autenticada, conteúdo registrado e publicação atômica com registro de operação | Assinatura local não recupera a identidade da Anthropic |
| Manutenção | Travamento entre ferramentas, observação nativa de processos e limpeza restrita de caches | Outros programas ainda podem iniciar ou escrever fora dessa coordenação |
| Cópia de segurança dos perfis | Checkpoint opcional do par Desktop/Code com verificação de conteúdo | Sem restauração; formato restrito; exclui Chaveiro e projetos externos; conteúdo não criptografado |
| Instalador e modo original + Duo | Conjunto completo verificado, versões retidas, ativação atômica do conjunto e operação em andamento vinculada à sua versão | Integração com instalação legada e interface de manutenção pendentes |
| Testes automatizados atuais | 145 testes aprovados localmente; resultados remotos desta etapa registrados no PR | Testes com dados inventados não comprovam login, SSO ou uso real do Code |
| Duas contas no Code gráfico | Primeiro Duo abriu na tela de entrada; login pausado pelo achado KC01 no Chaveiro | Conta efetiva, retorno do link de e-mail e continuidade ainda precisam ser observados |
| Reaproveitamento de preferências, MCPs e plugins | Proposta de importação seletiva documentada | Inventário, prévia, aplicação e sincronização ainda não implementados |
| Reconstrução automática do Duo | Fluxo planejado; construtor manual e watchdog de verificação disponíveis | Detecção, espera e reconstrução automática após atualização oficial ainda não implementadas |
| Base anterior de CI | 106 testes aprovados em Apple Silicon e Intel no commit `2d37bf6` | Evidência histórica, anterior ao instalador |
| Claude Duo em pasta descartável | 8 checagens reais aprovadas, agora também no destino privado: origem oficial, construção, conteúdo/assinatura e reserva do perfil padrão | Observação de processos simulada; aplicativo não aberto; contas não usadas |
| Aplicativo real na base anterior | 10 verificações aprovadas com Claude 2.42304.0, incluindo detecção de alteração após nova assinatura local | O executável do Claude não foi aberto e nenhuma conta foi usada nesses testes |
| Instalação na sua máquina | Conjunto versionado instalado; Duo construído e verificado em destino privado com observação nativa real | Personal/Trabalho na Lixeira por solicitação; dados legados preservados; candidato sem liberação para contas reais |

Referências: [CI da base conferida](https://github.com/guibrbs/multi-claude-desktop/actions/runs/39061863713),
[evidências](evidence/integrity-maintenance.json) e
[limitações técnicas](LIMITATIONS_AND_ROADMAP.md).
As evidências da base do instalador estão em
[toolset-installation.json](evidence/toolset-installation.json). A etapa de
preparação do laboratório, com os 145 testes e hashes atuais, está em
[gui-preparation.json](evidence/gui-preparation.json). O destino privado foi
ensaiado em pastas descartáveis. Esse registro histórico precede a decisão de
usar somente a sessão habitual. A preparação real e o bloqueio da primeira
abertura constam em [gui-first-launch.json](evidence/gui-first-launch.json);
nenhum login ou migração de perfis foi realizado.

## Ordem de execução

| Etapa | Entrega | Quando consideraremos pronta | Sua participação |
|---|---|---|---|
| 1. Instalação consistente | Implementada e testada em pastas descartáveis; falta transição da instalação em uso | Interrupção, adulteração e concorrência não ativam um conjunto incompleto | Nenhum login nos testes de código |
| 2. Revisão de segurança e preparação | Revisar instalador, origem dos arquivos e requisitos do teste gráfico | Evidências e limites registrados; ambiente descartável preparado | Confirmar tipos de conta e recursos de que precisa |
| 3. Duas contas na interface | Validar Desktop, Code e autenticação no original e na cópia | Matriz gráfica aprovada para os tipos de conta declarados | Fazer os logins diretamente no Claude |
| 4. Atualização e recuperação | Detectar atualização do original e reconstruir somente a cópia | Espera por aplicativos fechados, cenários de falha e recuperação ensaiados | Encerrar tarefas para os ensaios combinados |
| 5. Dados existentes | Oferecer migração e restauração compatíveis, se quiser preservar o uso atual | Recuperação ensaiada em cópias; origem preservada e exclusões documentadas | Escolher migrar ou começar com perfis novos |
| 6. Operação gráfica e distribuição | Instalação, verificação, atualização e remoção compreensíveis | Fluxos necessários executáveis pela interface, sem comandos no uso diário | Experimentar os fluxos de uso |
| 7. Piloto e manutenção | Liberar uma versão identificada e acompanhar mudanças | Critérios de liberação atendidos e registro das versões testadas | Usar o piloto e comunicar problemas sem enviar segredos |

A etapa 3 é a condição de viabilidade: falhas de autenticação ou troca de conta
impedem a liberação. A etapa 5 é necessária antes de migrar ou substituir seus
perfis existentes; o primeiro ensaio pode usar perfis novos. A distribuição
pública exige trabalho adicional de assinatura e revisão descrito na etapa 6.

## 1. Instalar as ferramentas como uma única versão

Problema atual: copiar vários scripts e arquivos auxiliares manualmente pode
deixar versões incompatíveis misturadas se a operação for interrompida.

- Preparar cada versão completa em uma pasta privada, com lista exata dos
  arquivos esperados, seus conteúdos e permissões.
- Validar a origem do pacote por uma referência previamente conferida. Um
  manifesto e arquivos adulterados juntos não comprovam autenticidade.
- Recusar arquivos faltantes, extras, links, destinos inseguros e pacotes
  incompatíveis; tratar configuração e manifesto como dados.
- Preparar e verificar os componentes necessários antes de ativar a versão.
  Definir como o compilador local e suas falhas entram nesse processo.
- Ativar o conjunto por uma troca atômica e manter a versão anterior das
  ferramentas para uma reversão controlada.
- Garantir que uma operação já iniciada continue usando uma única versão,
  inclusive seus scripts internos, bibliotecas e arquivos de compilação.
- Testar instalação concorrente, atualização durante uma operação, falta de
  espaço, falha de compilação, permissões insuficientes e encerramento abrupto
  antes/depois da ativação. Recusar ambientes sem a operação atômica necessária.
- Reconhecer instalações incompletas após reinício sem apagar ou promover
  automaticamente arquivos de origem incerta.
- Projetar a transição da instalação legada sem sobrescrever scripts em uso
  antes de uma mudança revisada. Desenvolver primeiro em pastas descartáveis.
- No modo original + cópia, reservar o perfil Desktop e Code padrão ao
  original e validar a configuração da única cópia. Manter a origem oficial
  fora dos destinos de publicação.

**Saída:** conjunto completo e identificável, ativação testada, versão anterior
retida e inspeção de falhas. Voltar as ferramentas não significa voltar o
Claude ou restaurar seus dados. Esta entrega está implementada em código e
testada em pastas descartáveis. O despachante é publicado antes da referência
ativa e deve ser compatível com o protocolo das duas versões; essas são duas
operações atômicas separadas. Detalhes em
[TOOLSET_INSTALLATION.md](TOOLSET_INSTALLATION.md). Instalar nos seus diretórios
reais e converter os atalhos legados permanecem etapas separadas.

## 2. Revisar segurança e preparar o ensaio gráfico

- Manter um inventário dos pontos que leem configuração, criam processos,
  escrevem arquivos, verificam assinaturas, compilam código e apagam caches.
- Rever os novos componentes e ampliar testes adversariais nos limites de
  formatos, tamanhos, permissões, concorrência e operações interrompidas.
  Reexecutar análise estática e a suíte apropriada a cada mudança.
- Definir quando conferir o conteúdo instalado e como comunicar uma mudança.
  Hoje o clique diário não realiza a verificação integral do aplicativo.
- Separar nos diagnósticos: origem oficial, integridade da cópia, versão,
  compatibilidade gráfica e identidade da conta observada. Cada informação
  precisa indicar quando foi verificada ou se permanece desconhecida.
- Preparar o ensaio do original e de uma cópia na sessão habitual do usuário,
  com pastas novas para o Duo e projetos descartáveis. O original usa seu perfil
  real existente; não apagá-lo para obter um cenário de primeira execução.
  `@apps user` permite construir o Duo em `~/Applications` privado sem escrever
  nos apps compartilhados. O [roteiro gráfico](GUI_VALIDATION_PT_BR.md) começa
  pela revisão dos atalhos e da cópia Personal que pode compartilhar o padrão.
  Conferir também manutenção legada concorrente, registro de aplicativos e Dock.
  Não criar outro usuário no macOS nem trocar HOME.
- Registrar versões exatas de macOS, arquitetura, Claude e ferramentas.
  O mínimo macOS 12 dos auxiliares não comprova suporte do próprio Claude.
- Confirmar tipos de login necessários: pessoal, organização e SSO, se usado;
  Code local e outros recursos que você realmente pretenda utilizar.
  Para o primeiro ensaio, o usuário confirmou login por link de e-mail, sem
  SSO. O retorno desse link precisa funcionar para o app e a conta corretos.
- Documentar a perda de identidade/permissões nas cópias e verificar possíveis
  efeitos no Chaveiro, permissões do macOS, subprocessos e recursos do Code.
- Diferenciar as proteções do nosso iniciador da configuração efetiva do
  original, que continua sendo lançado pelo fluxo oficial do macOS.
- Definir um teste de continuidade entre lançamento e manutenção. O bloqueio
  atual coordena nossas ferramentas; ainda não coordena todos os lançamentos
  nem impede um programa externo de abrir o perfil.

**Saída:** candidato identificado, roteiro de teste e lista explícita de
recursos suportados, pendentes e recusados. Sem alegação de porcentagem de
segurança. Problemas conhecidos de execução indevida, perda de dados ou uso da
conta errada precisam ser resolvidos antes do piloto.

## 3. Validar duas contas no Desktop e no Code

Você fará os logins dentro do próprio Claude. Os testes usarão tarefas sem
conteúdo privado e pastas descartáveis. Não será necessário entregar senhas,
tokens, cookies, códigos de recuperação ou exportações do Chaveiro.
Na matriz abaixo, A e B correspondem ao original e à cópia. A conta atribuída
ao original não depende de ser a pessoal ou a de trabalho.

| Teste | Comportamento a observar |
|---|---|
| Entrar em A e depois B; repetir na ordem inversa | Cada janela mostra a conta esperada |
| Reabrir os dois aplicativos e reiniciar o macOS | Sessões e identificação permanecem corretas |
| Conversar e abrir Code em ambos simultaneamente | Cada tarefa usa a conta e a configuração esperadas |
| Retomar tarefas após fechar e reabrir | Continuidade correta no perfil correspondente |
| Sair e entrar novamente em B enquanto A continua | A mantém a sessão e suas tarefas |
| Renovar ou revogar autenticação | Efeito limitado ao perfil esperado, ou limitação registrada e modo recusado |
| Concluir login pelo navegador e SSO, se necessário | Retorno para a janela e conta corretas |
| Abrir pelo Dock, Finder e atalhos | Destino e perfil corretos, inclusive com cópias antigas retidas |
| Abrir original e cópia; tentar iniciar uma cópia legada com o perfil padrão | Original e cópia principal usam dados distintos; conflito legado reconhecido; manutenção recusada com aplicativos ativos |
| Usar configuração local do Code | Shell, hooks, MCP e configurações de projeto não causam mistura inesperada |
| Reaproveitar preferências e extensões selecionadas | Configuração importada funciona; autenticação e ajustes próprios do Duo preservados; importador ainda pendente |
| Solicitar permissões e usar os recursos declarados | Funcionamento registrado para cada identidade de aplicativo |

O iniciador atual rejeita todos os argumentos, inclusive URLs. O fluxo de
retorno do login precisa ser observado: se depender de um argumento legítimo,
será necessária uma solução restrita e testada, preservando as proteções contra
comandos e parâmetros arbitrários.

Nome e cor do ícone ajudam a distinguir janelas; a conta efetiva deve ser
confirmada na interface e no contexto do Code. Usar marcadores inofensivos e
projetos separados para observar configurações, sem coletar credenciais ou
publicar conversas. Separar projetos também reduz erros humanos; continua sem
criar uma barreira de acesso entre programas do mesmo usuário.

**Saída:** relatório por versão e tipo de conta, com resultados e limitações.
Qualquer troca inesperada de conta ou identidade ambígua interrompe a liberação.
Se as cópias modificadas forem incompatíveis, registrar o impedimento. Uma
investigação do app oficial sem modificações será uma decisão separada;
o protótipo gráfico permanece adiado até essa necessidade ser demonstrada.

## 4. Atualizar e recuperar sem confundir aplicativos e perfis

- Implementar o fluxo de detecção, espera e reconstrução da única cópia descrito
  acima, mantendo o atualizador oficial no original. Ensaiar a atualização,
  reconstrução e nova verificação; exigir aplicativos Desktop fechados antes
  da manutenção, sem encerrar tarefas silenciosamente.
- Testar original em uso, cópia em uso e os dois abertos quando a atualização
  for detectada: mostrar atualização pendente e aguardar. Juntar eventos
  repetidos e revalidar qual versão oficial está pronta antes de reconstruir.
- Testar atualização da origem no meio da construção, mesma versão com conteúdo
  diferente, falha do observador, reinício e instalações concorrentes. Recusar
  publicação sem verificação e registrar resultado incerto para inspeção.
- Observar o atualizador interno das cópias e alterações de identidade,
  permissões ou conteúdo. Definir um fluxo suportado sem depender de modificações
  privadas do atualizador ou de desativar verificações do macOS.
- Repetir a matriz essencial de login e Code depois da atualização.
- Ensaiar falha de assinatura, origem indisponível, falta de espaço, versão
  incompatível e interrupção antes/depois da troca de cada componente.
- Mostrar quais componentes mudaram e distinguir uma operação preparada,
  concluída ou de estado incerto. Estado incerto exige inspeção.
- Testar o destino de abertura com cópias anteriores retidas, inclusive pelo
  Dock e pelo retorno do navegador. Uma cópia antiga não deve ser lançada como
  recuperação improvisada.
- Definir retenção e remoção revisadas para versões, registros, compilações
  temporárias, checkpoints e caches em quarentena. Proteger dados sensíveis e
  evitar esgotar o armazenamento, inclusive por cópias parcialmente concluídas.

**Saída:** atualização e recuperação reproduzíveis com dados de teste,
incluindo instruções claras para falhas. A troca atômica do nome no disco e os
ensaios de encerramento de processo não certificam resistência a falta de
energia. Versão anterior guardada não autoriza downgrade sobre dados migrados.

## 5. Preservar os dados existentes, se houver migração

O reaproveitamento de configurações solicitado é uma entrega distinta da
migração de contas/histórico. Desenvolver primeiro inventário e prévia, com
dados inventados, conforme [PROFILE_REUSE_PT_BR.md](PROFILE_REUSE_PT_BR.md).
Depois ensaiar importação seletiva, conflitos e sincronização em uma direção;
repetir a matriz de autenticação. Não copiar segredos ou estado de conta por
uma regra genérica de backup ou para evitar uma reconexão necessária.

- Escolher entre começar com perfis vazios ou reaproveitar os dados atuais.
  O original fica com o par Desktop/Code padrão; a cópia usa um par exclusivo.
  Ensaiar a volta ao original de dados usados por uma cópia Pessoal legada,
  incluindo histórico, permissões, autenticação e recursos do Code.
- Definir a desativação dos atalhos e da configuração da cópia Pessoal legada
  para evitar que ela abra o mesmo perfil do original. Preservar arquivos e
  dados até uma transição revisada; não remover aplicativos automaticamente.
- Conferir o inventário de metadados reais antes de copiar. O checkpoint atual
  recusa links, atributos estendidos e outros objetos; uma recusa precisa de
  uma solução de formato revisada, sem remover metadados do perfil original.
- Com os aplicativos fechados, preparar uma cópia compatível em destinos novos
  e conferir conteúdo, versão e comportamento. Preservar a origem.
- Ensaiar a restauração em pastas novas com aplicativo/schema compatíveis,
  verificando continuidade de histórico, configurações e tarefas do Code.
- Documentar o que exige novo login e o que fica fora: Chaveiro, permissões do
  macOS, repositórios externos e outros dados fora dos dois perfis.
- Definir proteção de armazenamento, criptografia apropriada e descarte dos
  checkpoints. Dados copiados podem conter sessões e código privado; permissões
  locais restritas não criptografam o conteúdo.
- Separar restauração de dados, reversão de ferramentas e downgrade do Claude;
  cada operação exige sua própria validação de compatibilidade.

**Saída:** procedimento de migração e recuperação ensaiado, origem preservada
e resultado aceito por você antes da troca dos perfis em uso. O checkpoint já
existente é um pré-requisito parcial. Restauração ainda não está implementada.

## 6. Tornar a operação gráfica e preparar a distribuição

- Começar com o ícone oficial e o da única cópia. Avaliar a necessidade de uma
  pequena interface de manutenção depois das validações.
- Oferecer instalação, estado, atualização, inspeção de falhas e remoção por
  fluxos compreensíveis. Informar o perfil afetado e pedir encerramento das
  tarefas sem encerrá-las silenciosamente.
- Explicar pré-requisitos, espaço em disco, versões testadas e incompatibilidades
  antes de aplicar mudanças. Tratar proxies e políticas corporativas exigidas
  como requisitos de compatibilidade, preservando a política da organização.
- Permitir remover as nossas ferramentas preservando os perfis. Apagar dados
  deve ser uma ação específica, com destino e consequência visíveis.
- Revisar README e ajuda para alinhar promessas às evidências, incluindo conta,
  atualização, espaço de APFS e recuperação. Tornar as orientações legadas
  claramente distinguíveis das instruções de uma versão liberada.
- Para distribuição pública, definir embalagem verificável, assinatura e
  notarização dos componentes próprios, proteção das credenciais de publicação
  e dependências fixadas. Isso pode exigir uma conta Apple Developer; não é
  necessário para continuar os testes atuais de código e pastas descartáveis.
- Preparar versão/tag, manifesto do pacote, notas de versão e teste de
  instalação/remoção em ambiente limpo. Revisão externa das partes sensíveis
  deve anteceder a distribuição pública.

**Saída:** fluxo de uso gráfico validado para o escopo anunciado. Assinar nosso
instalador não concede a ele nem às cópias a identidade da Anthropic. A
compilação de auxiliares ainda depende das Command Line Tools; empacotar
binários próprios seria outra decisão, com validação de origem correspondente.

## 7. Liberar um piloto e manter a compatibilidade

- Liberar primeiro uma versão identificada para uso acompanhado, com perfis
  novos e projetos sem dados sensíveis.
- Registrar problemas com dados mínimos: versões, etapa, resultado e mensagem
  sanitizada. Sem anexar perfis, checkpoints, ambiente de processos ou tokens.
- Vincular cada liberação a um commit, pacote conferido, CI e relatório gráfico.
  CI de Apple Silicon/Intel comprova os testes automáticos nessas máquinas;
  suporte gráfico em cada arquitetura exige ensaio correspondente.
- Revisar mudanças upstream e novas versões do Claude/macOS antes de declararem
  compatibilidade. Repetir testes de conta, assinatura, atualização e recuperação
  quando o comportamento afetado mudar.
- Definir como suspender uma versão com problema e oferecer recuperação
  compatível. Manter histórico de limitações e instruções de suporte.

**Saída:** versão utilizável dentro de um escopo explícito, com manutenção
prevista. O trabalho continua por novas versões e problemas concretos; uma
contagem crescente de testes não representa progresso rumo a segurança de 100%.

## Critérios para liberar o uso

- Instalação completa e atualização sem mistura de versões demonstradas.
- Testes automáticos e análise estática aprovados no código a liberar.
- Desktop e Code funcionando com ambas as contas na matriz declarada.
- Retorno de login, identidade das janelas e roteamento pelo macOS validados.
- Original preservado, perfis padrão reservados e reconstrução da cópia após
  atualização oficial testada com aplicativos ativos, fechados e em falha.
- Falhas e recuperação ensaiadas; migração condicionada a restauração compatível.
- Rotina gráfica e remoção que preserve dados verificadas.
- Evidências, origem dos artefatos e limitações disponíveis para revisão.
- Ausência de pendências conhecidas de uso da conta errada, execução indevida ou
  perda de dados dentro do escopo anunciado.

Os dois aplicativos continuarão com os acessos do mesmo usuário do macOS.
Isolamento entre contas contra um programa local malicioso exige uma barreira
do sistema operacional e não será certificado por este roadmap. Se uma
limitação de assinatura, autenticação ou política corporativa impedir o uso
pretendido, a conclusão correta será manter esse modo experimental ou recusá-lo.

## Como vamos trabalhar

Cada etapa terá mudanças revisáveis, commits no seu fork, testes proporcionais
ao que mudou e atualização do PR. O PR continua em rascunho enquanto os critérios
necessários estiverem pendentes. Implementação, evidência automatizada e teste
gráfico serão registrados separadamente.

Não fixamos datas antes de resolver a autenticação gráfica. O instalador já foi
desenvolvido e testado em ambiente descartável; a maior incerteza é o comportamento das duas contas
e das permissões nas cópias modificadas. Sua participação será necessária nos
logins e na avaliação do piloto. Desenvolvimento e testes automatizados usam
dados inventados. Uma futura migração, caso escolhida, envolve copiar arquivos
privados e seguirá o procedimento revisado da etapa 5.

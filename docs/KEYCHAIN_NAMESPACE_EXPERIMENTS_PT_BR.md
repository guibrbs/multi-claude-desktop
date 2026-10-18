# Experimentos para separar o nome do armazenamento seguro

Em 17/10/2026, dois protótipos descartáveis foram preparados e abertos sem login,
com autorização do usuário para cada abertura. **O Duo instalado não foi
substituído.** O bloqueio de liberação do [primeiro ensaio](KEYCHAIN_FIRST_LAUNCH_PT_BR.md)
continua: os experimentos não aprovam duas contas reais nem o Code gráfico.

## Resultado observado

| Experimento | Mudanças | Resultado |
|---|---|---|
| Nome interno e auxiliares | `CFBundleName` próprio, quatro auxiliares renomeados e reassinados | Abriu, mas ainda pediu `Claude Safe Storage`; usuário negou. Hipótese insuficiente. Também houve pedido de Documentos. |
| Nome de produto do pacote | `package.json.productName` próprio no ASAR; auxiliares originais preservados | Abriu sem pedidos de permissão, conforme interface e confirmação do usuário. Consulta apenas de atributos encontrou uma entrada com o nome próprio esperado. A tela exibida foi o login deslogado do Desktop (claude.ai/login na janela do app), o mesmo estado do Duo antigo; ver reabertura abaixo. |

Os dois protótipos foram fechados com ⌘Q. O observador nativo confirmou os apps
Desktop parados após cada ensaio. Nenhum login foi feito, nenhum valor secreto
foi coletado, e nenhuma autorização de acesso ao Chaveiro foi concedida pela
automação. Não foram apagadas entradas do Chaveiro ou pastas de perfil.
O segundo app pode ter criado sua própria chave como parte da inicialização;
essa entrada foi preservada. A ausência de aviso não comprova ausência de
outras consultas silenciosas nem separação de toda a autenticação.

## Correção da hipótese anterior

Mudar só `CFBundleName` não resolveu. O pacote distribuído declara
`productName: "Claude"`. O
[bootstrap do Electron 44.7.2](https://github.com/electron/electron/blob/v44.7.2/lib/browser/init.ts)
atribui esse valor a `app.name`. Assim, os metadados do bundle não são a única
fonte de nome relevante. A combinação do teste negativo, da definição no
pacote e do teste positivo aponta para esse mecanismo; não é uma reconstrução
completa de todos os caminhos do binário da Anthropic.

Na segunda amostra, os nomes dos auxiliares e `CFBundleName` ficaram iguais aos
da origem. A alteração semântica no ASAR foi limitada a `productName` em
`package.json`. Foram atualizados tamanho, offsets afetados e os hashes desse
membro, além do hash do cabeçalho em `ElectronAsarIntegrity`. Nenhum payload
JavaScript foi alterado. O executável principal e o bundle externo foram
reassinados localmente, como já ocorre na construção atual; os quatro
auxiliares mantiveram seus arquivos e assinaturas originais.

A consulta de confirmação pediu **somente atributos** da entrada com o nome
exato da segunda amostra. Retorno de dados secretos e de referências foi
explicitamente desativado; interação de autenticação foi configurada para
falhar, sem fallback interativo. A consulta confirmou existência, não leu o
valor, não editou ACLs e não comparou chaves. Isso não prova que todos os
segredos usados pelo aplicativo estejam separados.

## Verificações de construção

- Origem oficial verificada por identidade Anthropic, assinatura aninhada e
  Gatekeeper. Versões do experimento fixadas em Claude 2.42304.0 / Electron 44.7.2;
  versões diferentes são recusadas para nova revisão.
- Comparação de 4.964 entradas da origem com a primeira amostra, incluindo os
  cinco executáveis antes/depois da assinatura. Somente os campos de assinatura
  previstos foram normalizados; formatos e disposições desconhecidos falham.
- Na segunda amostra, comparação de todos os 508 membros do ASAR e dos demais
  arquivos da origem. Apenas a semântica `package.json.productName` mudou no
  pacote; payloads externos a esse membro ficaram byte a byte iguais. Auxiliares
  e seus recursos/assinaturas ficaram iguais aos da origem.
- Assinatura aninhada e comparação de conteúdo da segunda amostra passaram
  também depois do ensaio gráfico. Conteúdo da origem ficou igual durante cada
  preparação; nenhuma ferramenta instalou ou substituiu um app em uso.
- 25 novos testes offline aprovados: 12 sobre comparação de Mach-O/auxiliares e
  13 sobre limites e alterações do ASAR. A distribuição de CI cobre agora 170
  testes sem lacunas ou duplicatas: 86 perfis/experimentos, 59 armazenamento e
  25 instalador. Os 145 testes anteriores permanecem evidência da implementação
  `b938c7d`; não se infere um resultado remoto novo a partir desse histórico.

A primeira tentativa de preparar a segunda amostra recusou arquivos deduplicados
do ASAR antes de criar o app. A inspeção encontrou 25 pares que compartilham
intervalos exatamente iguais. O parser passou a aceitar esses aliases, com
testes adicionais; continua recusando sobreposições parciais e qualquer alias
do intervalo de `package.json`. A tentativa recusada ficou registrada, sem
fallback para uma cópia menos verificada.

O pedido de Documentos do primeiro experimento coincidiu com app e dados de
ensaio dentro dessa pasta. Não foi demonstrado o gatilho exato. A segunda
amostra e seus dados novos ficaram fora de Documentos e não pediram a permissão.

## Reabertura e comparação por logs

Em 17/10/2026, às 22:07, a mesma amostra foi reaberta pelo agente, a pedido do
usuário, com a mesma pasta de dados descartável e sem login. Ela mostrou a tela
deslogada padrão do Desktop: janela própria do app, logo Claude, “Continuar com
o Google” e o aviso de cookies, que ficou sem resposta. Nenhum pedido do
Chaveiro apareceu, e o app fechou limpo com ⌘Q.

Os logs locais (`main.log`) dos três apps de teste mostram o mesmo fluxo
deslogado (`sign_in_cookie_present: false`), com as mesmas rotinas do Desktop
(Code, Cowork, `startup-sign-in`). A única diferença é o Chaveiro:

| App | Travamento até o estado de login | `safeStorage` |
|---|---|---|
| Duo antigo (`b938c7d`) | 88,7 s (`event-loop-stall`) | `isEncryptionAvailable=false` após a negação |
| 1º protótipo (auxiliares) | 41,0 s | `isEncryptionAvailable=false` após a negação |
| Amostra `productName` (2 aberturas) | ~1 s | sem aviso |

O registro do Duo antigo (G11) já descrevia `claude.ai/login` depois da negação.
Portanto, a “introdução anterior do Desktop” não era um estado comparável, e a
troca de `productName` não mudou a tela de entrada. O User-Agent não foi medido.
O login real continua não testado.

## Integração no construtor de produção

No modo `original-copy` (o Duo), o construtor agora dá à cópia o
`productName` `<nome> Claude`, por exemplo `Duo Claude`. Com isso, o Electron
procura a chave `Duo Claude Safe Storage`. O modo legado não muda: instalações
antigas continuam com a mesma chave e não são deslogadas.

Como funciona, em C, sem Python no uso diário:

- **Mesmo tamanho.** No `package.json`, `"Claude"` vira `"Duo Claude"`, e o
  mesmo número de bytes de espaço insignificante, fora de strings, é removido.
  O arquivo mantém o tamanho, nenhum offset do ASAR se move e o cabeçalho
  mantém o comprimento. Mudam só os hashes desse membro (hash e blocos) e, no
  `Info.plist`, o hash `ElectronAsarIntegrity` do cabeçalho.
- **Gravação só no staging.** `integrity product-name` grava num arquivo
  exclusivo ao lado do `app.asar` e troca com `rename` atômico. Se falhar, o
  arquivo temporário é apagado. Um temporário que sobrar de uma execução
  interrompida faz a construção seguinte ser recusada.
- **Verificação que não confia no staging.** O registro de integridade
  **regenera o arquivo esperado a partir da origem** e exige igualdade byte a
  byte com a cópia, com o hash do `Info.plist` conferido contra o cabeçalho.
  Antes disso, ele recusa: hash de `package.json` da origem divergente de
  qualquer bloco; mais de um `package.json` no topo; layout de entrada
  diferente do compacto esperado (inclusive `unpacked`); payload compartilhado
  com outro membro; `productName` diferente de `"Claude"`, duplicado, aninhado
  ou com chave escapada; espaço insignificante insuficiente; e um
  `ElectronAsarIntegrity` da origem que não confere com o cabeçalho. Uma
  verificação semântica independente compara as formas sem espaço.
- **Duo já instalado.** A política de vínculo passou para
  `MCD_BUILD_CONFIG_ORIGINAL_COPY_3`. Qualquer Duo construído antes falha
  na verificação e precisa ser reconstruído para receber a correção.

Validação:

- 12 novos testes offline (`tests/test_product_name.py`): cópia com nome
  próprio, digests e tamanho preservados; legado byte a byte igual; adulteração
  pós-construção do JavaScript, do nome ou do hash do `Info.plist` detectada;
  adulteração entre gravação e registro recusada antes da publicação; seis
  pacotes e quatro layouts de arquivo não revisados recusados; vários blocos
  re-selados; escrita interrompida por limite de tamanho e diretório sem
  escrita deixam o arquivo intacto, sem temporário; nomes não validados
  recusados; e atualização da origem com reconstrução.
- O gravador em C, aplicado ao `app.asar` real do Claude 2.42304.0, foi aceito
  pelo verificador Python independente do experimento: 508 membros, só
  `productName` alterado, mesmo tamanho e 167 bytes diferentes.
- Construção descartável real com o código novo: identidade, aninhamento e
  Gatekeeper da origem; construção, verificação e assinatura aninhada do Duo;
  reserva dos perfis padrão; e arquivos críticos da origem inalterados. Nenhum
  app foi aberto e nenhum perfil real foi usado.

O Duo instalado em `~/Applications` **não foi reconstruído**. Isso é uma
mudança no seu sistema e fica para a sua decisão.

## Interface web depois do login (correção de 17/10/2026)

A [reabertura](#reabertura-e-comparação-por-logs) comparou só a tela
**deslogada**, e a conclusão de que o nome não afetava a experiência Desktop
estava errada. Logado com `Claude Duo`, o app mostrou avisos da versão web
("Experimente o Claude Code no desktop", "Código no seu celular") e os botões
da janela sobre o título.

Causa, conferida no código:

- O Electron 44.7.2 monta o User-Agent com o nome do app **sem espaços**
  (`BuildApplicationUserAgent`, `RemoveChars(name, " ")`) e nomeia a chave como
  `<nome> Safe Storage`, com espaços. Ele também apara o `productName` (`trim`).
- O claude.ai ativa a interface Desktop com `claudeAppBindings` **e** um token
  `claude/` no User-Agent (`/claude(nest|gov)?\/([^ ]+)/i`,
  `indexOf("claude/")`). `Claude Duo` gerava `ClaudeDuo/2.42304.0`, que falha.

Correção: o `productName` passou a ser `<nome> Claude` (`Duo Claude`), com
token `DuoClaude/2.42304.0`, aceito por essas checagens, e chave
`Duo Claude Safe Storage`. Uma checagem `includes(" Claude/")` do claude.ai,
usada em mobile e em um caminho de impressão, continua diferente do original.
Paridade total exigiria um nome que, sem espaços, fosse exatamente `Claude`,
ou seja, com espaço no meio (por exemplo `Claud e`). Essa opção foi descartada
pela legibilidade. A confirmação final é a interface logada sem os avisos web.

## O que falta antes de integrar

1. ~~Preservar a experiência Desktop~~ **descartado em 17/10/2026, 22:07.**
   A suspeita de uma página web diferente não se confirmou (ver
   [reabertura](#reabertura-e-comparação-por-logs)).
2. ~~Integrar verificações ao construtor de produção~~ **feito em 17/10/2026.**
   Ver [integração no construtor](#integração-no-construtor-de-produção).
3. **Repetir abertura, fechamento e reconstrução**, incluindo outra arquitetura
   quando houver a origem correspondente. Os ensaios reais desta rodada são arm64.
   Assinaturas ad-hoc podem provocar novas solicitações após reconstruções.
4. **Retomar G01–G11 com o usuário**, começando por login por e-mail, retorno ao
   app correto e identidade efetiva do Code. Contas simultâneas, saída de uma
   conta sem afetar a outra e continuidade ainda não foram testadas.

Os [resultados sanitizados](evidence/keychain-namespace-experiments.json)
separam os fatos observados das hipóteses. Não há proteção contra um processo
malicioso do mesmo usuário, nem garantia absoluta de segurança.

## Ferramentas experimentais

Os scripts abaixo somente preparam novas cópias; não abrem aplicativos, não
instalam em Applications e não importam perfis ou acessam o Chaveiro:

- [Preparação por nome de produto](../scripts/prepare-product-name-probe.py), com
  [alteração e verificação limitada do ASAR](../scripts/asar_product_name.py).
- [Experimento anterior](../scripts/prepare-namespace-probe.py), cuja reprodução
  exige `--reproduce-helper-only-failure` porque a separação falhou na interface.

Não são comandos do conjunto versionado de produção. Uma nova abertura de
software modificado ou uma nova permissão sensível é revisada na hora da ação.

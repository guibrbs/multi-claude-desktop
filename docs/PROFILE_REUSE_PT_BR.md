# Reaproveitar a configuração do original no Claude Duo

Requisito acrescentado em 17/10/2026: a mesma pessoa usa duas contas e quer
reaproveitar suas preferências, MCPs, skills e plugins sem configurar tudo à mão.
Este documento começou como **proposta de implementação**. Em 17/10/2026 o
usuário escolheu um caminho mais simples, descrito logo abaixo e implementado;
o importador seletivo completo continua como proposta.

## Implementado: compartilhamento por links (decisão do usuário)

[`scripts/share-code-profile.py`](../scripts/share-code-profile.py) faz o Code
do Duo (`~/.claude-duo`) usar os **mesmos arquivos** do original (`~/.claude`):

- Links: `CLAUDE.md`, `skills`, `output-styles`, `tools`, `plugins` e cada
  `projects/<projeto>/memory`. Uma memória salva por um app aparece no outro.
- `settings.json` é copiado **uma vez**. Ficam de fora chaves que escolhem
  outra conta ou outro provedor (`apiKeyHelper`, `forceLogin*`, auxiliares de
  credencial e `env` com `ANTHROPIC_*`, `AWS_*`, `CLAUDE_CODE_USE_*` etc.); só o
  nome dessas chaves aparece na saída. `extraKnownMarketplaces` do Duo é mesclado.
  Depois disso, ajustes no Duo são preservados.
- Nunca lê nem grava `.claude.json`, sessões, histórico, transcrições
  (`projects/*/*.jsonl`), caches, políticas ou estado de conta: só a lista acima.
- Padrão é prévia sem alteração. `--apply` exige o Duo fechado. Item já
  existente no Duo é recusado, ou movido (nunca apagado) para
  `.share-backup-<data>` com `--backup-existing`. Links que apontam para outro
  lugar, origens que já são links e pastas graváveis por outros são recusados.
  Rodar de novo é idempotente e liga memórias de projetos novos do original;
  memória que só existe no Duo é mantida e informada, sem mistura.

Cuidados dessa escolha, que contraria a proposta original de cópias próprias:

- Plugins, hooks e skills são código executável e passam a valer nos dois
  apps. Instale e remova plugins pelo original; uma instalação feita no Duo
  grava caminhos de `~/.claude-duo` no inventário compartilhado.
- As duas contas leem e escrevem as mesmas memórias. Não guarde nelas
  informação que uma das contas não deva ver.
- Checkpoints do perfil Code do Duo passam a ser recusados, porque o helper
  de checkpoint não segue links. Isso é intencional.
- Um `--apply` interrompido pode deixar parte dos links. Rodar de novo completa
  os que faltam; nada do original é alterado.
- O script roda a partir do checkout revisado; não faz parte do conjunto
  versionado de ferramentas.

## Comportamento pretendido

O original é a referência inicial. O Duo oferece importar os itens compatíveis
e informa o que depende de reconexão ou revisão. Depois, detectar mudanças e
atualizar somente itens previamente escolhidos, mantendo ajustes exclusivos do
Duo. Uma mudança de código executável ou de acesso precisa de nova decisão;
uma escolha anterior não aprova qualquer plugin ou comando futuro.

As duas contas mantêm seus logins, sessões e históricos separados. Nome, e-mail,
plano, organização e recursos da conta B vêm do serviço após seu login. Não
substituir esses dados pelos da conta A para reproduzir a aparência do perfil.
Instruções e preferências pessoais podem ser reaproveitadas seletivamente.

Essa distinção é necessária: a documentação da Anthropic informa que
`~/.claude.json` guarda tanto MCPs e preferências como sessão de login e decisões
de confiança. `CLAUDE_CONFIG_DIR` também redireciona dados que incluem sessões e
plugins. Por isso não copiar esse arquivo inteiro nem compartilhar a pasta de
configuração por links. [Arquivos e precedência de configurações](https://code.claude.com/docs/en/settings).

## Tratamento por categoria

| Categoria | Tratamento proposto |
|---|---|
| Preferências de interface e comportamento | Importar somente chaves documentadas, com formato e semântica conhecidos; chaves desconhecidas ficam pendentes |
| Instruções pessoais, skills e comandos | Selecionar conteúdo e dependências, manter cópias próprias e verificar mudanças; podem conter informação privada ou instruções executáveis |
| Definições de MCP | Reaproveitar nomes, transporte e configuração revisados; separar credenciais e verificar comandos, argumentos, endpoints e caminhos |
| Plugins e marketplaces | Reproduzir a seleção por origem e revisão/versão exatas; verificar pacote e dependências; instalação/ativação é etapa explícita |
| Hooks, permissões, diretórios adicionais e variáveis | Revisão específica: podem executar comandos, ampliar acesso ou escolher outro provedor/conta; não herdar automaticamente |
| Conectores e extensões ligados ao serviço | Reconectar na conta B quando exigido; reaproveitar uma declaração local não transfere autorização ou licença |
| MCPs com senha, token, header ou configuração criptografada | Nova conexão no Duo por padrão; reaproveitamento futuro de um segredo de terceiro exige escolha específica, sem transferir o login do Claude |
| Configuração de projetos já abertos pelos dois | Inventariar o que ambos já carregam do projeto; evitar duplicar definições e preservar decisões de confiança de cada perfil |
| Sessões, histórico, cookies, OAuth, Chaveiro, cache e estado de conta | Excluir da importação; usar os fluxos oficiais de login |
| Política gerenciada pela organização | Não copiar para contornar a política da outra conta; respeitar a configuração efetiva e registrar incompatibilidades |

Na documentação atual, o Code local também pode receber MCPs da configuração
Desktop, além dos arquivos de Code/projeto. Isso torna insuficiente conferir só
`settings.json`: o ensaio deve confirmar a origem e precedência efetivas em cada
app. Plugins podem incluir hooks e servidores MCP; copiar sua pasta de cache
não demonstra uma instalação válida. [Desktop: configurações, MCPs e plugins](https://code.claude.com/docs/en/desktop).

O contrato inicial será de cópias próprias por perfil. Não apontar o Duo para
todo `~/.claude`, `~/.claude.json` ou o perfil Desktop do original. Compartilhar
executáveis instalados no sistema é diferente de compartilhar dados mutáveis
de autenticação, cache ou configuração. Um endpoint de MCP pode dar acesso aos
mesmos dados externos nos dois apps; separar o login do Claude não separa esses
dados automaticamente.

## Fluxo de implementação

1. **Inventário local e prévia sem alteração.** Definir adaptadores para as
   versões do Desktop/Code testadas. Ler somente fontes selecionadas, com
   limite de tamanho/profundidade, sem seguir links, arquivos especiais ou
   caminhos externos. Rejeitar JSON ambíguo, inclusive chaves duplicadas.
   Diagnóstico mostra categorias, ações e conflitos; nunca valores de segredos.
2. **Plano por item.** Validar chaves por lista de permissões e esquema,
   preservando exclusões de autenticação em todas as estruturas. Não tentar
   identificar todo segredo pelo nome da chave ou por expressões regulares.
   `command`, `args`, URLs e textos livres também podem conter segredos.
   Comandos/hooks/plugins não são executados durante inventário e prévia.
3. **Reprodução controlada.** Definir separadamente copiar dados declarativos,
   instalar uma extensão verificada e ativar código. Referências de plugin
   devem vincular origem, versão/revisão e conteúdo; não substituir uma revisão
   indisponível pela última versão. Duplicatas de MCP ou fontes incompatíveis
   precisam de resolução visível, preservando a configuração do destino.
4. **Aplicação com os apps fechados.** Usar bloqueio e observação de processos
   existentes; revalidar hashes e identidade da origem/destino. Preparar em
   staging privado e publicar a mudança sem sobrescrita parcial. Para vários
   arquivos, definir um protocolo de recuperação antes de prometer atomicidade
   do conjunto. Não editar os arquivos do original nem restaurar seu estado de
   autenticação sobre B. Falha mantém uma operação inspecionável.
5. **Atualizações em uma direção.** Guardar hashes do último conteúdo importado
   e comparar original, versão importada e Duo. Mudança só no original pode
   atualizar um item anteriormente aprovado; mudança nos dois gera conflito.
   Excluir algo no original não apaga automaticamente a personalização do Duo.
   Alteração no Duo não volta para o original. Não sincronizar durante sessões
   ativas nem misturar esse processo com a atualização do bundle do aplicativo.
6. **Validação.** Usar primeiro arquivos e extensões inertes inventados no
   [laboratório](GUI_VALIDATION_PT_BR.md). Depois validar os itens reais
   selecionados, sem enviar o inventário privado ao GitHub. Login e
   reconexões continuam a cargo do usuário na interface oficial.

O instalador de ferramentas tem inventário e protocolo fixos. Implementar um
novo componente de importação exige revisar empacotamento, compatibilidade,
atualização e recuperação; não distribuir um script solto fora do conjunto.

## Critérios de aceitação adicionais

- Conta A permanece ativa ao importar, usar ou remover uma extensão em B.
  Confirmar a conta efetiva no Code; preferências iguais não provam isso.
- Origem permanece inalterada e o Duo carrega somente os itens escolhidos.
  Credenciais fictícias de Claude, tokens de MCP e URLs com segredos usados em
  fixtures não aparecem na saída nem são transferidos como preferências.
- Configurações com `env`, headers, helper de credenciais, provedor, hooks,
  permissões amplas, caminhos externos ou esquema desconhecido são identificadas
  e tratadas pela regra específica; não passam por uma cópia genérica.
- Arquivos alterados após a prévia, links/hardlinks, metadados inseguros,
  concorrência, falta de espaço e interrupções não ativam uma importação parcial
  silenciosa. A recuperação é ensaiada antes de oferecer aplicação automática.
- Um item personalizado no Duo sobrevive à sincronização; conflitos ficam
  pendentes. Troca de versão ou revisão de extensão reabre a validação necessária.
- Reconexão de terceiros, SSO e limitações de organização são mostradas como
  pendências reais; o sistema não promete copiar autorizações que o serviço
  vincula à conta.

Primeira entrega proposta: inventário e prévia com fixtures, sem gravação de
perfil. A aplicação e a sincronização dependem desse contrato e da prova de
autenticação independente no laboratório. A preferência por uso gráfico e a
prioridade de segurança permanecem; não é necessário criar um gerenciador
nativo novo para iniciar essa validação.

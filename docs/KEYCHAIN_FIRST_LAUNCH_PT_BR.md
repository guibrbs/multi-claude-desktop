# Primeiro ensaio gráfico: acesso ao Chaveiro bloqueado

Em 17/10/2026, a preparação real foi concluída e o usuário abriu o Claude Duo
pelo Finder. Antes de fazer login, apareceu um pedido de acesso à entrada
**Claude Safe Storage** do Chaveiro, solicitando a senha do macOS. O usuário
confirmou que escolheu **Negar**. A interface observada depois estava na tela
de entrada do Claude, sem conta conectada. O ensaio de contas foi pausado.

**O candidato ainda não está liberado para uso com contas reais.** O pedido
não demonstra roubo de dados, nem comprova mistura de contas. Demonstra uma
dependência de uma entrada existente que a separação de pastas não resolveu.
Não há resultado aprovado de independência de autenticação.

**Atualização da investigação:** o
[experimento de nome interno e auxiliares](KEYCHAIN_NAMESPACE_EXPERIMENTS_PT_BR.md)
não resolveu o aviso. Uma segunda amostra, mudando o nome do produto no pacote,
abriu sem pedidos de permissão e gerou uma entrada com nome próprio, confirmada
somente por atributos. A experiência Desktop e as contas continuam pendentes;
o protótipo não substituiu o Duo instalado. A hipótese baseada só em
`CFBundleName` era incompleta.

## O que foi observado

- Candidato construído com a implementação `b938c7dcd90d755aa1457c0118bb7884440a082c`,
  a partir do Claude oficial 2.42304.0, em macOS arm64. O framework declara
  Electron 44.7.2.
- Instalador versionado, construção, assinatura aninhada e verificação completa
  de conteúdo passaram na preparação real, usando os observadores de processos
  de produção. Os arquivos críticos da origem e a configuração legada ficaram
  iguais antes/depois dessa preparação.
- Duo instalado em `~/Applications/Claude Duo.app`, com pastas novas de Desktop
  e Code e uma configuração de ensaio separada. Nenhum usuário macOS adicional.
- A pedido do usuário, Personal e Trabalho foram movidos para a Lixeira. Os
  dados dos perfis e a configuração legada foram preservados. Isso não é uma
  migração desses dados para o Duo.
- A primeira abertura foi feita pelo usuário. O texto do aviso e a escolha de
  negar são relatos do usuário; a tela de entrada foi observada pela automação
  de interface. Nenhuma leitura do conteúdo do Chaveiro foi feita pela auditoria.
- `CFBundleIdentifier` é distinto, mas **`CFBundleName` continua `Claude` nos
  dois apps**. Só o nome de exibição foi alterado para `Claude Duo`.
- O ASAR dos dois apps tem o mesmo SHA-256. Os quatro auxiliares continuam com
  os nomes `Claude Helper`, incluindo as variantes GPU, Renderer e Plugin.

Os [dados sanitizados](evidence/gui-first-launch.json) identificam o candidato
sem publicar perfis, conversas, e-mails, links de login ou segredos.

## Explicação técnica e seus limites

O [safeStorage do Electron](https://www.electronjs.org/docs/latest/api/safe-storage)
usa o Chaveiro no macOS para proteger chaves de criptografia de dados locais.
A documentação também alerta que mudanças de assinatura podem produzir novos
pedidos de acesso. Uma chave de criptografia local não é, por definição, a
senha da conta Anthropic. Autorizar seu uso pode ampliar o acesso do aplicativo
aos dados que essa chave protege; não deve ser tratado como um aviso cosmético.
O proprietário, o conteúdo e o histórico da entrada preexistente não foram
inspecionados; não é possível atribuí-la exclusivamente ao original ou a uma
cópia legada com base no texto do aviso.

No código upstream da versão correspondente, a inicialização define o serviço
como `app_name + " Safe Storage"` e a conta como `app_name`:
[ElectronBrowserMainParts](https://github.com/electron/electron/blob/v44.7.2/shell/browser/electron_browser_main_parts.cc).
Sem um nome sobrescrito, `Browser::GetName()` usa o nome do executável, que no
macOS vem de `CFBundleName`:
[Browser](https://github.com/electron/electron/blob/v44.7.2/shell/browser/browser.cc),
[ApplicationInfo](https://github.com/electron/electron/blob/v44.7.2/shell/common/application_info_mac.mm).
O nome preservado é uma explicação consistente com o aviso observado. A fonte
upstream e os metadados não são uma prova de todos os caminhos do binário
distribuído pela Anthropic, nem inventariam o conteúdo da entrada solicitada.

Há uma segunda dependência desse mesmo nome. O
[iniciador de subprocessos do Electron](https://github.com/electron/electron/blob/v44.7.2/shell/app/electron_main_delegate_mac.mm)
procura auxiliares pelo nome de produto ou pelo nome do app e aborta se não os
encontrar. Por isso, **mudar somente `CFBundleName` não é uma correção validada**.
O construtor atual preserva os auxiliares assinados e sua verificação de
integridade recusa alterações fora das previstas. Não foi feita essa mudança
isolada no aplicativo instalado.

Uma análise estática com REA reteve evidências parciais do ASAR. Houve limites
de memória, tempo e grafo semântico; ela não certifica o aplicativo inteiro.
O hash declarado no ASAR para um binding nativo desempacotado difere do arquivo
distribuído. O arquivo observado tem os mesmos bytes no original e no Duo; a
análise foi continuada registrando a divergência, sem tratá-la como conteúdo
autenticado pelo hash interno do ASAR. As assinaturas verificadas durante a
preparação são uma evidência separada, não uma explicação automática da
divergência. Os IDs e limites estão no registro sanitizado.

## Próxima correção e critérios para retomar

É preciso projetar e testar uma identidade própria para o armazenamento seguro
sem quebrar a descoberta dos auxiliares. Ainda não foi demonstrado um mecanismo
suportado por esse aplicativo que faça isso preservando o empacotamento atual.
Alterar nomes/caminhos/plists dos auxiliares ou inserir código no ASAR ampliaria
as modificações e exigiria nova análise de assinaturas, integridade e permissões.
Não aplicar esses caminhos diretamente na instalação em uso.

1. Examinar uma solução em cópia descartável, sem login, com uma lista exata das
   mudanças e suas consequências. Preservar a origem oficial e os perfis reais.
2. Confirmar que processo principal e auxiliares abrem nas arquiteturas cobertas,
   que o armazenamento continua criptografado e que a cópia deixa de solicitar
   a entrada do original. Qualquer nova permissão sensível é revisada antes de
   autorizá-la; não ler valores secretos para comprovar a separação.
3. Verificar persistência após fechar/reabrir e reconstruir. A assinatura local
   pode voltar a provocar pedidos de acesso após uma atualização, mesmo com um
   nome próprio. Um nome diferente também não cria isolamento entre processos
   que podem acessar os mesmos arquivos do usuário.
4. Só então retomar G01/G11 e, depois, retorno do link de e-mail, conta efetiva
   do Code, sessões simultâneas e os demais casos do roteiro. A ausência de um
   aviso, sozinha, não aprova esses casos.

Não apagar a entrada do original, copiar sua chave, liberar acesso permanente,
desativar criptografia ou modificar as políticas do Chaveiro para obter um
resultado aprovado. Outro usuário macOS foi recusado pelo usuário e não é um
pré-requisito que possa ser introduzido silenciosamente. Até uma solução ser
validada, usar o Claude oficial e manter o login do Duo pausado.

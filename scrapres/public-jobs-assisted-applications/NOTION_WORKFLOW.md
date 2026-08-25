# Workflow manual do Notion

O projeto nunca armazena token do Notion. A outbox é local, revisável e destinada
à conexão autenticada do Codex ou a outra integração explicitamente autorizada.

## Preparar

```bash
npm run rank
npm run notion:preview
npm run notion:approve -- --reference REFERENCIA
npm run notion:pending
```

Somente itens com `approved: true` e
`delivery_status: approved_for_manual_send` podem ser sincronizados.

O título do banco vem de `NOTION_DATABASE_TITLE` e usa `Job Applications` como
padrão.

## Contrato de sincronização

Quando `$notion-track-application` estiver disponível, o agente deve:

1. usar a conexão autenticada, sem pedir ou salvar token no projeto;
2. localizar o banco configurado e seu data source atual;
3. deduplicar por `Job URL`, depois `Source Job ID`, empresa e cargo;
4. criar ou atualizar usando a outbox revisada;
5. preservar status e campos não relacionados em páginas existentes;
6. buscar a página novamente e verificar os dados persistidos;
7. somente após a verificação, executar:

   ```bash
   node notion-outbox.mjs mark-sent \
     --reference REFERENCIA \
     --page-url URL_NOTION
   ```

A aprovação da outbox não autoriza enviar candidatura nem alterar o status para
`APPLIED`.

## Revogar

```bash
node notion-outbox.mjs revoke --reference REFERENCIA
```

Revogar o estado local não apaga uma página já criada no Notion.

## Recuperação

- Se o Notion falhar depois que documentos forem aceitos, retome apenas a etapa do
  Notion.
- Se uma página puder já ter sido criada, consulte-a antes de tentar novamente.
- Nunca use `mark-sent` sem verificar uma URL de página real.

# 0009. Fonte do banco Chinook

## Status

Aceito

## Data

2026-10-08

## Contexto

O `sqlite-consulta` usa o banco de exemplo Chinook. O arquivo não pode ser versionado (`.gitignore` ignora `*.sqlite`), mas precisa ser obtido de forma reproduzível e verificável, pois um arquivo adulterado poderia trazer dados maliciosos ou estrutura inesperada.

## Decisão

- Fonte oficial: repositório [lerocha/chinook-database](https://github.com/lerocha/chinook-database), licença MIT, release **`v1.4.5`**, arquivo `Chinook_Sqlite.sqlite`.
- URL: `https://github.com/lerocha/chinook-database/releases/download/v1.4.5/Chinook_Sqlite.sqlite`.
- Verificação: tamanho de 1.067.008 bytes e SHA-256 `bdf635be69850bd3be09c9a2dbeef7ddfb80036bd3ef3381383cd03b61e4a61a`, calculado em 2026-10-08. A release não publica um digest próprio, então esse valor fica fixado no código.
- Obtenção pelo comando `uv run sqlite-consulta download-db`, que grava em `SQLITE_CONSULTA_DATA_DIR` (padrão `~/.cache/mcp-labs/sqlite-consulta/`) como `chinook-v1.4.5.sqlite`, só depois de verificar o hash. O servidor confere o hash de novo ao iniciar.
- Os testes não dependem do download: usam um banco pequeno criado no próprio teste.

## Consequências

- Ambiente reproduzível e protegido contra troca do arquivo na origem ou no caminho.
- Atualizar a versão do Chinook exige alterar URL e hash juntos, em um PR revisado.
- O primeiro uso exige acesso à internet.

## Alternativas consideradas

- **Versionar o `.sqlite`:** contraria o `.gitignore` e a regra de não versionar bancos.
- **Gerar o banco a partir do `Chinook_Sqlite.sql`:** mais lento e acrescenta um passo sem benefício de segurança, já que o hash do `.sqlite` basta.
- **Baixar do branch `master`:** conteúdo mutável, impossível fixar hash.

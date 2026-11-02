# Publicação — notas para o mantenedor

Este arquivo é uma lista de preparação e não precisa ser incluído no pacote de extensão nem no catálogo.

## Antes do primeiro Release

- [ ] Criar o repositório público `marcosnett/LoopsubD-trazo`.
- [ ] Revisar e confirmar a licença e a compatibilidade de redistribuição do código original NB70 e de quaisquer componentes incorporados. O arquivo Python atual declara `GPL-3.0-or-later`; manter a licença compatível e os avisos de copyright exigidos.
- [ ] Confirmar a grafia oficial do nome do aplicativo (IngeTrazo/Ingetrazo) conforme a marca/documentação oficial.
- [ ] Confirmar que o ZIP final contém a estrutura exigida pelo instalador e testar a instalação limpa.
- [ ] Criar um Release `v0.4.9` com o ZIP instalável anexado.
- [ ] Gerar SHA-256 do ZIP final e usar exatamente esse valor na ficha do catálogo.
- [ ] Preparar a ficha de catálogo conforme o TEMPLATE.toml e as instruções atuais do repositório oficial de extensões.
- [ ] Submeter a ficha por Pull Request e acompanhar a validação/revisão.

## Observação sobre licença e autoria

O cabeçalho do código Python declara `SPDX-License-Identifier: GPL-3.0-or-later`. Este pacote de publicação inclui a licença GPL-3.0-or-later. Antes de publicar, confirme que essa declaração está correta para todo o código distribuído e que os avisos e atribuições da implementação original foram preservados. Não remova cabeçalhos de copyright existentes.

## Hash do pacote

Gerar depois de criar o ZIP definitivo:

```bash
sha256sum LoopsubD-trazo-0.4.9.zip
```

Não reutilizar o hash de um ZIP experimental anterior: qualquer alteração no arquivo muda o hash.

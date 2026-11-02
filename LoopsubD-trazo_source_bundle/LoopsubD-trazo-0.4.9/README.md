# LoopsubD-trazo

**LoopsubD para IngeTrazo — versão 0.4.9**  
Extensão de subdivisão de superfícies com Control Cage editável.

[English version below](#english)

## Sobre

LoopsubD-trazo é uma extensão para o IngeTrazo que cria uma superfície subdividida vinculada a uma cópia independente da malha original, chamada **Control Cage**. A Cage permanece editável e pode ser usada para atualizar a superfície subdividida sem criar cópias adicionais.

Este projeto é uma implementação para IngeTrazo relacionada ao projeto LoopsubD 2 para SketchUp. O desenvolvimento desta versão foi realizado por Marcos Benedete, preservando o crédito à implementação original de **NB70**. Consulte [CREDITS.md](CREDITS.md) para os créditos e [LICENSE](LICENSE) para os termos de distribuição.

## Recursos principais

- Subdivisão Loop com níveis configuráveis.
- Criação de uma superfície subdividida separada, mantendo a Control Cage original.
- Atualização da superfície vinculada, manual ou automaticamente.
- Edição da Cage com seleção individual e múltipla de vértices, arestas e faces.
- Suporte a Creases (arestas de vinco).
- Overlay de arestas, vértices, Creases e elementos selecionados.
- Preservação de materiais e atributos de faces compatíveis com a topologia.
- Suporte à triangulação de faces, inclusive polígonos e faces com furos, conforme os recursos disponíveis no IngeTrazo.
- Visibilidade automática da Cage: oculta no modo normal e revelada ao iniciar sua edição.
- Histórico Undo/Redo integrado ao fluxo de edição do IngeTrazo.

## Compatibilidade

Desenvolvido e testado com IngeTrazo **0.5.9** e **0.5.11**. A API de extensões do IngeTrazo pode evoluir; outras versões podem exigir ajustes. Recomenda-se testar em uma cópia do projeto antes de usar em trabalhos importantes.

## Instalação

1. Baixe o pacote ZIP da versão desejada na seção **Releases** deste repositório.
2. No IngeTrazo, abra o Gerenciador de Extensões.
3. Use a opção de instalar extensão a partir de arquivo e selecione o ZIP baixado.
4. Reinicie o IngeTrazo, se solicitado.

A instalação também poderá ser disponibilizada pelo catálogo comunitário do IngeTrazo após a aprovação da ficha de extensão.

## Fluxo básico

1. Selecione um grupo compatível com a malha que deseja subdividir.
2. Defina o nível de subdivisão e acione **Subdividir / Atualizar cópia**.
3. A extensão cria a superfície subdividida vinculada à Control Cage original.
4. Para editar, selecione a superfície subdividida e acione **Editar Cage**.
5. Edite vértices, arestas, faces e Creases. Atualize a superfície manualmente ou habilite a atualização automática.
6. Ao finalizar a edição, a Cage é ocultada e a superfície subdividida permanece visível. Para editar novamente, selecione a superfície e acione **Editar Cage**.

## Documentação

- [Histórico de versões](CHANGELOG.md)
- [Créditos](CREDITS.md)
- [Instruções de instalação](docs/installation.md)
- [English documentation](#english)

## Licença

Distribuído sob os termos da **GNU General Public License v3.0 or later (GPL-3.0-or-later)**. Consulte o arquivo [LICENSE](LICENSE). A atribuição à implementação original de NB70 deve ser mantida.

---

<a id="english"></a>

# LoopsubD-trazo (English)

**LoopsubD for IngeTrazo — version 0.4.9**  
A surface-subdivision extension with an editable Control Cage.

## About

LoopsubD-trazo is an extension for IngeTrazo that creates a subdivided surface linked to a separate copy of the original mesh, called the **Control Cage**. The Cage remains editable and can be used to update the linked subdivided surface without creating additional copies.

This is an IngeTrazo implementation related to the LoopsubD 2 project for SketchUp. This implementation is developed by Marcos Benedete and retains attribution to the original implementation by **NB70**. See [CREDITS.md](CREDITS.md) and [LICENSE](LICENSE).

## Main features

- Loop subdivision with configurable levels.
- Separate subdivided surface while preserving the original Control Cage.
- Manual and automatic updates of the linked surface.
- Single and multi-selection of Cage vertices, edges, and faces.
- Crease-edge support.
- Viewport overlay for edges, vertices, Creases, and selected elements.
- Preservation of compatible materials and face attributes.
- Face triangulation support, including polygons and faces with holes, subject to IngeTrazo capabilities.
- Automatic Cage visibility: hidden in normal mode and revealed when Cage editing starts.
- Undo/Redo integration with the IngeTrazo editing workflow.

## Compatibility

Developed and tested with IngeTrazo **0.5.9** and **0.5.11**. The IngeTrazo extension API may evolve, and other versions may require adjustments. Test on a copy of your project before using it on important work.

## Installation

1. Download the ZIP package for the desired version from this repository's **Releases** page.
2. Open the Extension Manager in IngeTrazo.
3. Choose the option to install an extension from a file and select the downloaded ZIP.
4. Restart IngeTrazo if requested.

The extension may also become available through the IngeTrazo community catalog after its submission is reviewed and accepted.

## Basic workflow

1. Select a group containing the mesh you want to subdivide.
2. Set the subdivision level and click **Subdivide / Update Copy**.
3. The extension creates a linked subdivided surface while preserving the original Control Cage.
4. To edit, select the subdivided surface and click **Edit Cage**.
5. Edit vertices, edges, faces, and Creases. Update the surface manually or enable automatic updates.
6. When editing ends, the Cage is hidden and the subdivided surface remains visible. To edit again, select the surface and click **Edit Cage**.

## License

Distributed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**. See [LICENSE](LICENSE). Attribution to the original implementation by NB70 must be retained.

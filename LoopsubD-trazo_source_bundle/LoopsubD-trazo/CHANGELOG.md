# Changelog

## 0.4.9 — First public release

- Automatically hides the Control Cage in normal mode and reveals it when Cage editing starts.
- Allows Cage editing to be initiated by selecting the linked subdivided surface; direct selection of the Cage remains supported.
- Hides the Cage again when editing ends, including when the IngeTrazo editing mode is exited externally and detected by the extension.
- Keeps the Cage faces visually hidden during editing by default while preserving the subdivision surface, wireframe overlay, vertices, Creases, and selection highlights.
- Includes configurable subdivision levels, manual/automatic surface updates, multi-selection and manipulation of vertices and edges, face selection, Crease support, and Undo/Redo integration.
- Preserves compatible materials and supports polygon triangulation, including tested faces with holes.
- No geometry or material transparency is used to implement the Cage visibility workflow.

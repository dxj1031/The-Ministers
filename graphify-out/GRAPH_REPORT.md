# Graph Report - e:\the ministers  (2026-07-11)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 63 nodes · 119 edges · 10 communities (7 shown, 3 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 1 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8

## God Nodes (most connected - your core abstractions)
1. `createRuntime()` - 9 edges
2. `Minister` - 8 edges
3. `walkChildren()` - 8 edges
4. `walk()` - 8 edges
5. `getReact()` - 7 edges
6. `boot()` - 7 edges
7. `resolve()` - 7 edges
8. `compileAttr()` - 7 edges
9. `collectProps()` - 6 edges
10. `walkFor()` - 6 edges

## Surprising Connections (you probably didn't know these)
- `boot()` --calls--> `getReact()`  [EXTRACTED]
  app/front/support.js → app/front/support.js  _Bridges community 5 → community 3_
- `walkFor()` --calls--> `getReact()`  [EXTRACTED]
  app/front/support.js → app/front/support.js  _Bridges community 5 → community 1_
- `compileAttr()` --calls--> `resolve()`  [EXTRACTED]
  app/front/support.js → app/front/support.js  _Bridges community 6 → community 1_
- `createRuntime()` --calls--> `resolve()`  [EXTRACTED]
  app/front/support.js → app/front/support.js  _Bridges community 6 → community 4_
- `walkText()` --calls--> `resolve()`  [EXTRACTED]
  app/front/support.js → app/front/support.js  _Bridges community 6 → community 5_

## Import Cycles
- None detected.

## Communities (10 total, 3 thin omitted)

### Community 1 - "Community 1"
Cohesion: 0.38
Nodes (12): collectProps(), compileAttr(), cssToObj(), hostPositionStyle(), kebabToCamel(), walk(), walkChildren(), walkComponent() (+4 more)

### Community 3 - "Community 3"
Cohesion: 0.25
Nodes (9): boot(), dcNameFromPath(), getReactDOM(), init(), parseDataProps(), parseDcDocument(), parseDcText(), rootNameForDocument() (+1 more)

### Community 4 - "Community 4"
Cohesion: 0.33
Nodes (6): createExternalModules(), createHelmetManager(), createPseudoSheet(), createRegistry(), createRuntime(), Placeholder()

### Community 5 - "Community 5"
Cohesion: 0.40
Nodes (5): createComponentFactory(), evalDcLogic(), getReact(), walkText(), warnUnresolved()

### Community 6 - "Community 6"
Cohesion: 0.50
Nodes (4): findTopLevelEquality(), parensWrapWhole(), resolve(), resolvePath()

## Knowledge Gaps
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `createRuntime()` connect `Community 4` to `Community 0`, `Community 3`, `Community 5`, `Community 6`?**
  _High betweenness centrality (0.007) - this node is a cross-community bridge._
- **Why does `resolve()` connect `Community 6` to `Community 0`, `Community 1`, `Community 4`, `Community 5`?**
  _High betweenness centrality (0.004) - this node is a cross-community bridge._
- **What connects `# TODO:` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
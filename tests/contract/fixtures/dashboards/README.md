# Golden-фикстуры дашбордов (D0.2)

Анонимизированные ответы живого `/rpc/getDashboard` (published-ветка,
`x-dl-api-version: 2`, конверт `{"entry": ...}` снят). Дата среза: **2026-07-18**.

Анонимизация детерминированная: id/ключи/логины/свободные тексты заменены
синтетическими, структура и формы полей не менялись (см. эпик D0 на доске
`Datalens SDK Kanban`, карточка `d365`).

| Файл | Класс | Что демонстрирует | Происхождение |
|---|---|---|---|
| `simple.json` | простой (текст + заголовок + один чарт, одна вкладка) | минимальный живой дашборд: title/text/widget items, канонический layout | live-проба D0 |
| `selectors_dataset.json` | селекторы sourceType=dataset | 4 dataset-селектора (select/date range), defaults c datasetFieldId, connections | sandbox (старый SDK) |
| `selectors_manual_two_tabs.json` | селекторы sourceType=manual + две вкладки | manual-селекторы с acceptableValues, межвкладочная структура | sandbox (старый SDK) |
| `group_control_manual.json` | group_control (manual) — прод-дашборд | группа селекторов: impactType/impactTabsIds/placementMode/width, buttonApply | прод (read-only) |
| `group_control_dataset.json` | group_control (dataset) | группа dataset-селекторов, две вкладки | sandbox (старый SDK) |
| `global_items_shared_selectors.json` | globalItems (shared-селекторы) + data.description | per-tab globalItems, оба канала описания (data.description + annotation) | sandbox (старый SDK) |
| `items_features.json` | pinned + enableActionParams + neuro_widget + image + styling | __fixHead/__fixGCont parents, enableActionParams на widget tab, neuro_widget, image (src/preserveAspectRatio), textSettings/backgroundSettings/hint | live-проба D0 |

Непокрытые классы (задокументированное отсутствие на 2026-07-18):

- **editor-чарты в дашборде** — у робот-токена нет прав Editor developer mode
  (403 на createEditorChart), читабельных прод-дашбордов с editor-чартами не
  нашлось (робот видит ~4000 свежих дашбордов, читаем один).
- **workbook-дашборд** — в доступности робота только folder-дашборды
  (`workbookId: null` во всех фикстурах).

`enableActionParams` и `neuro_widget` сняты live-пробой D0.5 (items_features):
оба ПЕРСИСТЯТСЯ через публичный /rpc (старый квирк d4b1 «strip on write»
на текущем API опровергнут).

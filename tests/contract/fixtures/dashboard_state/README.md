# Фикстуры стейтов дашборда

| Файл | Что это | Происхождение |
|---|---|---|
| `state_group_interval_widget_tab.json` | ответ `getEntryState`: группа селекторов, дата-интервал, вкладка чарта в очереди | живой стейт `21e04f18384`, 2026-11-16 |
| `state_action_params.json` | ответ `getEntryState`: action params `_ap_<guid>` двух чартов | живой стейт `298725dd251`, 2026-11-16 |
| `dashboard_group_interval_widget_tab.json` | минимальный `getDashboard` под первый стейт с теми же id элементов, групп и вкладок | синтетика |
| `dashboard_action_params.json` | минимальный `getDashboard` под второй стейт | синтетика |

Порядок ключей в живых ответах задаёт jsonb в US (сначала по длине ключа), а не UI.
Тесты сравнивают данные, а не порядок ключей.

# `cli_ble` jako MCP server pro lokální AI agenta

Tento návrh popisuje bezpečné propojení `cli_ble` s lokálním AI agentem,
například s modelem běžícím přes Ollama. Doporučené rozhraní je **MCP**
(Model Context Protocol): agent volá pojmenované nástroje a nedostává volný
přístup k PowerShellu, BLE UUID ani libovolným binárním zápisům.

První cíl je malý a ověřitelný: agent se připojí k již nakonfigurovanému ESP32,
odešle pojmenovaný příkaz, přijme odpověď a vrátí ji ve strojově čitelném tvaru.

## Proč MCP místo volání CLI příkazů modelem

Model nemá sám sestavovat například `--send UUID '...'`. Špatně vybraný UUID
nebo binární rámec může změnit nastavení zařízení. MCP server může naopak
vystavit jen povolené operace definované v `devices.json`:

- zařízení `test-led`;
- nástroje `led-on`, `led-off`, `esp-hi`;
- později například `temperature-read`, `fan-on` a `fan-off`.

`cli_ble.py` zůstane užitečné jako lidské diagnostické CLI. MCP vrstva nad ním
má být malé API pro agenta s kontrolovaným rozsahem oprávnění.

## Návrh prvních MCP tools

| Tool | Vstup | Výstup | Účel |
|---|---|---|---|
| `ble_list_devices` | bez vstupu | zařízení a dostupné tools | Agent zjistí, co smí ovládat. |
| `ble_device_info` | `device` | profil, dostupné tools, poslední adresa | Diagnostika a kontrola schopností. |
| `ble_run_tool` | `device`, `tool` | potvrzený výsledek operace | Bezpečné spuštění pojmenovaného nástroje. |
| `ble_read_value` | `device`, `value_id` | hodnota, jednotka, čas měření | Budoucí čtení teploty, vlhkosti nebo stavu. |
| `ble_health` | `device` | dostupnost, RSSI, odezva, firmware | Rychlá kontrola před akcí nebo při chybě. |

Pro první test stačí `ble_run_tool`. Má mapovat přímo na současné nástroje
`cli_ble.py -d test-led esp-hi`, `led-on` a `led-off`.

## Strukturovaný výsledek místo terminálového textu

MCP tool nemá vracet pouze barevný výpis CLI. Má vracet JSON, aby agent mohl
spolehlivě rozhodovat podle polí `ok`, `value` nebo `error`.

```json
{
  "ok": true,
  "device": "test-led",
  "tool": "esp-hi",
  "sent": "hi",
  "notifications": ["hello"],
  "latency_ms": 83
}
```

Pro senzor by odpověď mohla vypadat takto:

```json
{
  "ok": true,
  "device": "room-sensor",
  "value_id": "temperature",
  "value": 23.7,
  "unit": "degC",
  "sampled_at": "2026-09-01T12:34:56Z"
}
```

ESP by proto mělo vedle provedení akce vracet potvrzení stavu. Místo pouhého
`hello` lze postupně přejít například na `{"ok":true,"led":true}`. Textové
odpovědi mohou zůstat podporované během přechodu.

## Bezpečnostní hranice

- MCP server povolí pouze zařízení a tools uložené v `devices.json`.
- Obecný zápis do UUID (`--send`) nebude součástí běžných agentních tools.
- Klíče z `.env` se nikdy nevrací modelu, do logu ani do MCP odpovědi.
- Každá fyzická akce má být idempotentní: `fan-on` je bezpečnější než `toggle`.
- Rizikové akce mohou mít `requires_confirmation: true`; MCP tool pak vrátí
  požadavek na potvrzení místo provedení příkazu.
- Ventilátor, relé a podobné výstupy mají mít limit běhu a bezpečný stav po
  restartu či ztrátě spojení.

## Diagnostika a provoz

Užitečné jsou zejména `ping`/`health`, informace o RSSI, čas posledního
úspěšného spojení, doba odezvy a bezpečný auditní log. Log má zaznamenat
zařízení, tool, výsledek a čas, ale nikdy autentizační klíč ani jiné tajné
hodnoty.

Je vhodné rozlišovat chyby: zařízení nenalezeno, spojení selhalo,
autentizace selhala, timeout odpovědi a zařízení odmítlo příkaz. Agent pak
nezkouší naslepo stejný fyzický příkaz opakovaně.

## Doporučený postup implementace

- [x] Přidána sdílená vrstva `lib/device_runner.py` s `run_device_tool(...)`.
  Vrací strukturovaný výsledek o adrese, připojení, nesenzitivním zápisu,
  notifikacích, době běhu a typu chyby; `cli_ble.py` jej jen textově vypisuje.
- [ ] Vytvořit malý lokální MCP server s `ble_list_devices`, `ble_device_info`
  a `ble_run_tool`; povolit pouze entries z `devices.json`.
- [ ] Přidat na ESP `status` a potvrzení akcí ve strukturovaném JSON formátu,
  například stav LED a verzi firmware.
- [ ] Doplnit `value_id` a dekodéry pro senzory (`temperature_c`, `humidity_pct`,
  `fan_rpm`) v konfiguraci zařízení a vystavit `ble_read_value`.
- [ ] Přidat policy, auditní log, `ble_health`, timeouty a limity běhu pro
  fyzické výstupy; teprve potom dát agentovi přístup k ventilátoru či relé.

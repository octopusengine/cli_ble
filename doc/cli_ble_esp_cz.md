# `cli_ble` a ESP32-C3 přes BLE UART

Tento projekt umožňuje ovládat ESP32-C3 z příkazové řádky přes Bluetooth Low
Energy (BLE). ESP vystupuje jako BLE periférie, počítač s `cli_ble` jako BLE
centrála. Nejde o klasický sériový port Windows; data putují přes BLE službu
Nordic UART Service (NUS).

## Základní postup

1. Nahraj a spusť na ESP skript `esp_upy/test_ble_key.py`.
2. Ověř, že ESP inzeruje jméno podobné `octopus-led-48034`.
3. Zkontroluj definici zařízení:

   ```powershell
   python cli_ble.py device test-led info
   ```

4. Spusť pojmenovaný nástroj:

   ```powershell
   python cli_ble.py -d test-led led-on
   python cli_ble.py -d test-led led-off
   python cli_ble.py -d test-led led-toggle
   python cli_ble.py -d test-led esp-hi
   ```

Delší, ekvivalentní zápis je například:

```powershell
python cli_ble.py device test-led run led-on
```

## Protokol převzatý z Bluefruit Connect

Skript ESP vychází z mobilní aplikace **Bluefruit Connect** a jejího Control
Pad. Aplikace neposílá prosté znaky šipek, ale textové rámce níže. Jsou
definované v `utils.ble.bluefruit`:

| Tlačítko | BLE UART data | Chování v ukázce ESP |
| --- | --- | --- |
| UP | `b'!B516'` | zapnout LED |
| DOWN | `b'!B615'` | vypnout LED |
| LEFT | `b'!B714'` | zatím bez akce |
| RIGHT | `b'!B813'` | přepnout LED |
| F1 | `b'!B11'` | zatím bez akce |
| F2 | `b'!B219'` | zatím bez akce |
| F3 | `b'!B318'` | zatím bez akce |
| F4 | `b'!B417'` | zatím bez akce |

Proto `led-on` ve `devices.json` posílá `!B516` a `led-off` posílá `!B615`.
CLI hodnotu odešle jako UTF-8, takže výsledné bajty jsou stejné jako v zápisu
`b'!B516'` na ESP.

## BLE UART vrstva

Nordic UART Service pouze přenáší data; neurčuje, co `!B516` znamená. Tento
význam definuje aplikační kód ESP.

| UUID | Název | Směr z pohledu CLI |
| --- | --- | --- |
| `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | Nordic UART Service | služba |
| `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Nordic UART RX | CLI → ESP, zápis příkazů |
| `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Nordic UART TX | ESP → CLI, notifikace a odpovědi |

Označení RX/TX je z perspektivy ESP. CLI tedy zapisuje do RX a přijímá
notifikace z TX.

## Zařízení a nástroje

[`devices.json`](devices.json) skrývá technické UUID a Bluefruit rámce pod
pojmenovanými nástroji. Profil `nordic-uart` je společný pro zařízení, která
používají stejnou NUS službu. `test-led` obsahuje nástroje `led-on`, `led-off`,
`led-toggle` a `esp-hi`.

Při spuštění nástroje CLI nejprve vyhledá reklamní název s prefixem
`octopus-led-`. To je důležité, protože BLE adresa se může po restartu změnit.
MAC v konfiguraci slouží jako záloha.

Nové zařízení lze prozkoumat a přidat takto:

```powershell
python cli_ble.py --add octopus-led-48034
```

Příkaz hledá přesný reklamní název, vypíše GATT služby a chrání konfiguraci
proti duplicitě podle názvu i MAC adresy.

## Jednoduchý společný klíč

`test_ble_key.py` má hodnotu:

```python
KEY = 123
```

Lokální soubor `.env` má odpovídající hodnotu:

```text
KEY1=123
```

V `devices.json` je zařízení propojeno přes:

```json
"auth": {
  "environment": "KEY1"
}
```

Každý příkaz `-d test-led ...` odešle při novém spojení nejprve klíč a až poté
příkaz LED nebo `hi`. Klíč se nevypisuje ani nezapisuje do logu. ESP po přijetí
správného klíče odpoví `ok`; `esp-hi` pak vrátí ještě `hello`.

Toto je pouze jednoduchá kontrola přístupu. Klíč není kryptograficky chráněný;
pro skutečné zabezpečení je potřeba BLE párování a šifrování, případně vlastní
autentizační protokol.

## Diagnostika

Sken zařízení:

```powershell
python cli_ble.py -s --name octopus-led
```

Výpis GATT služeb podle aktuální MAC adresy:

```powershell
python cli_ble.py -c 48:31:B7:33:D0:36
```

Pro ověření, že ESP opravdu běží s klíčovým skriptem, můžeš zkusit raw zápis
bez klíče. Odpověď má být `unauthorized` a LED se nesmí změnit:

```powershell
python cli_ble.py -c 48:31:B7:33:D0:36 --send 6e400002-b5a3-f393-e0a9-e50e24dcca9e "!B516" --notify 6e400003-b5a3-f393-e0a9-e50e24dcca9e --listen 2
```

Pokud se LED i bez klíče změní, ESP stále běží se starším skriptem bez kontroly
klíče; nahraj a spusť `test_ble_key.py` a ESP restartuj.

## Náměty k dalšímu rozvoji

- [ ] Po odeslání klíče explicitně čekat na `ok`; při `unauthorized` neposílat
  následující nástroj.
- [ ] Přidat příkaz `status` nebo `led-state`, aby ESP přes notifikaci vracelo
  aktuální stav LED místo pouhého echa příkazu.
- [ ] Přidat do `devices.json` další zařízení a profily, například relé, PWM,
  teplotní čidlo nebo servo.
- [ ] Umožnit interaktivní průvodce nad `--add`, který nabídne rozpoznaný profil
  a vytvoří základní pojmenované nástroje až po potvrzení uživatele.
- [ ] Přidat BLE párování a šifrování pro zařízení, kde jednoduchý společný klíč
  nestačí.
- [ ] Zapisovat do logu časová razítka, název zařízení a název spuštěného
  nástroje pro pozdější diagnostiku.

# `cli_ble` — aktuální stav a další kroky

`cli_ble` je jednoduché multiplatformní rozhraní příkazové řádky pro Bluetooth Low Energy (BLE). Je postavené nad knihovnou [Bleak](https://github.com/hbldh/bleak), proto je určené pro Windows a Linux s funkčním Bluetooth adaptérem (na Linuxu také s BlueZ).

## Co už CLI umí

### Skenování zařízení

```powershell
python cli_ble.py -s
python cli_ble.py -s scan1.txt
python cli_ble.py -sa
python cli_ble.py -st
python cli_ble.py -s --name MeshCore
python cli_ble.py -s --address C6:04
python cli_ble.py -s --service 6e400001-b5a3-f393-e0a9-e50e24dcca9e
python cli_ble.py -s --service nus
```

- `-s` / `--scan` — sken okolních zařízení; výpis omezuje `scan.default` v `cli_ble.json` (nyní 20).
- `-s scan1.txt` — stejný výpis uloží v UTF-8 i do souboru.
- `-s -a` nebo `-sa` — vypíše všechna zařízení nalezená během skenu.
- `-s -t` nebo `-st` — seřadí zařízení podle RSSI a vypíše nejsilnější; limit určuje `scan.top` v `cli_ble.json` (nyní 10).
- `--name TEXT` — ponechá jen zařízení, jejichž název obsahuje zadaný text.
- `--address TEXT` — ponechá jen zařízení, jejichž adresa obsahuje zadaný text či prefix.
- `--service UUID` — ponechá jen zařízení, která v reklamních datech oznamují dané UUID služby; přepínač lze opakovat.
- `cli_ble.json` může obsahovat krátké GATT aliasy. Vestavěné aliasy `nus`, `nus-rx` a `nus-tx` odpovídají službě Nordic UART, zapisovací RX charakteristice a notifikační TX charakteristice. Plné UUID zůstávají vždy podporované.
- Název zařízení je v interaktivním terminálu žlutý; adresa a RSSI bílé. Při přesměrování do souboru se žádné ANSI barvy nezapisují.

### Připojení a průzkum GATT

```powershell
python cli_ble.py -c AA:BB:CC:DD:EE:FF
```

Příkaz se připojí k zařízení podle aktuální BLE adresy a vypíše jeho GATT služby, charakteristiky, jejich UUID a oprávnění (`read`, `write`, `notify` atd.) i deskriptory charakteristik s jejich handly. BLE adresa může být u některých zařízení soukromá a měnit se; v tom případě je vhodné zařízení před připojením znovu skenovat.

```powershell
python cli_ble.py -c AA:BB:CC:DD:EE:FF --read-all-safe
```

`--read-all-safe` čte pouze charakteristiky, které samy deklarují oprávnění `read`, a zkusí přečíst také nalezené deskriptory. Nevytváří zápis ani notifikace. Pokud zařízení čtení konkrétní hodnoty odmítne, CLI vypíše chybu s UUID (u deskriptoru i handlem) a pokračuje další položkou.

### Čtení, zápis a notifikace

```powershell
python cli_ble.py -c AA:BB:CC:DD:EE:FF --receive CHARACTERISTIC_UUID
python cli_ble.py -c AA:BB:CC:DD:EE:FF --notify CHARACTERISTIC_UUID --listen 30
python cli_ble.py -c AA:BB:CC:DD:EE:FF --send CHARACTERISTIC_UUID "text"
python cli_ble.py -c AA:BB:CC:DD:EE:FF --send CHARACTERISTIC_UUID "01 ff 7a" --hex
python cli_ble.py -c AA:BB:CC:DD:EE:FF --notify nus-tx --listen 30
python cli_ble.py -c AA:BB:CC:DD:EE:FF --send nus-rx "text"
```

- `--receive` (také `--read`, `--rec` a záměrně podporované chybné `--recieve`) přečte jednu hodnotu.
- `--notify` odebírá notifikace po dobu určenou `--listen`.
- `--send` zapisuje text v UTF-8; `--hex` zapíše binární data z hexadecimálního zápisu.
- Zobrazené hodnoty obsahují čitelný UTF-8 text, pokud je možný, a vždy hexadecimální podobu.

Zápis do neznámé charakteristiky se nedoporučuje: může měnit konfiguraci zařízení, zejména u BMS/baterií.

### Diagnostika, nápověda a konfigurace

```powershell
python cli_ble.py --examples
python cli_ble.py -v -c AA:BB:CC:DD:EE:FF --timeout 25
python cli_ble.py -c AA:BB:CC:DD:EE:FF --pair --retries 2 --log session.log
```

- `-e` / `--examples` zobrazí anonymizované příklady příkazů.
- `-v` / `--verbose` zapne log Bleak a úplný traceback. Bez něj CLI vypisuje krátkou barevně odlišenou chybu a praktický tip.
- `--timeout` řídí délku skenu i maximální dobu připojení.
- `--pair` požádá operační systém o BLE párování před připojením. Ve Windows se může objevit systémové okno pro potvrzení nebo PIN; na Linuxu vyžaduje funkční BlueZ a jeho agenta pro párování.
- `--retries COUNT` přidá zadaný počet dalších pokusů o připojení. Mezeru mezi pokusy řídí `--retry-delay` (výchozí hodnota 2 sekundy).
- Pokud zařízení při připojení není nalezeno, CLI automaticky provede krátký nový scan. Nenajde-li původní adresu, vypíše okolní zařízení s nejsilnějším signálem a upozorní na možnou změnu soukromé BLE adresy.
- `--log FILE` zapisuje běžný výstup, warningy a chyby do připojovaného UTF-8 textového logu bez ANSI barev.
- `cli_ble.json` obsahuje limity výsledků skenu.
- `.env` podporuje proměnnou `BLE_KEY`; knihovní funkce `get_ble_key()` ji načte. Klíč se zatím automaticky nikam neposílá, protože autentizační protokol závisí na konkrétním zařízení.

## Poslední test: MeshCore-Yenda Tag

Zařízení bylo nalezeno jako:

```text
C6:04:19:D0:3F:CA    MeshCore-Yenda 💳 Tag, RSSI -58 dBm
```

RSSI `-58 dBm` znamená poměrně silný signál. Připojení na adrese `C6:04:19:D0:3F:CA` proběhlo úspěšně a zařízení poskytlo tři GATT služby.

### 1. Generic Access Profile (GAP)

```text
00001800-0000-1000-8000-00805f9b34fb  Generic Access Profile
```

GAP je standardní BLE služba pro základní identitu a chování zařízení.

| UUID | Charakteristika | Oprávnění | Význam |
| --- | --- | --- | --- |
| `00002a00-0000-1000-8000-00805f9b34fb` | Device Name | `read`, `write` | Zobrazené jméno zařízení. Lze jej přečíst; zápis může změnit jméno, proto jej bez potřeby nepoužívat. |
| `00002a01-0000-1000-8000-00805f9b34fb` | Appearance | `read` | Standardní číselná kategorizace typu zařízení pro BLE klienty. |
| `00002a04-0000-1000-8000-00805f9b34fb` | Peripheral Preferred Connection Parameters | `read` | Preferované intervaly, latence a timeout spojení navržené periferií. Jsou užitečné pro diagnostiku kvality nebo úspornosti spojení. |
| `00002aa6-0000-1000-8000-00805f9b34fb` | Central Address Resolution | `read` | Informace související s řešením soukromých BLE adres. Vysvětluje, proč se u některých zařízení může adresa ze skenu měnit. |

Bezpečné čtení názvu:

```powershell
python cli_ble.py -c C6:04:19:D0:3F:CA --receive 00002a00-0000-1000-8000-00805f9b34fb
```

### 2. Generic Attribute Profile (GATT)

```text
00001801-0000-1000-8000-00805f9b34fb  Generic Attribute Profile
```

Tato standardní služba spravuje změny struktury služeb zařízení.

| UUID | Charakteristika | Oprávnění | Význam |
| --- | --- | --- | --- |
| `00002a05-0000-1000-8000-00805f9b34fb` | Service Changed | `indicate` | Zařízení může klientovi potvrzenou indikací oznámit, že se změnila tabulka GATT služeb. Užitečné při aktualizaci firmwaru nebo dynamické změně služeb. |

CLI v současné verzi podporuje `notify`; případnou podporu `indicate` je vhodné ověřit a doplnit testem. Bleak často obě formy odběru obslouží přes stejné `start_notify()`, ale je dobré to ověřit na konkrétním zařízení.

### 3. Nordic UART Service (NUS)

```text
6e400001-b5a3-f393-e0a9-e50e24dcca9e  Nordic UART Service
```

To je nejdůležitější služba pro budoucí komunikaci s MeshCore tagem. NUS vytváří sériový kanál nad BLE; sama neurčuje obsah zpráv, pouze jejich přenos.

| UUID | Název | Oprávnění | Směr z pohledu CLI | Použití |
| --- | --- | --- | --- | --- |
| `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Nordic UART TX | `notify` | tag → CLI | Příchozí data a odpovědi tagu. |
| `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Nordic UART RX | `write`, `write-without-response` | CLI → tag | Příkazy či datové rámce posílané tagu. |

Poznámka k názvům: `TX` a `RX` jsou pojmenované z perspektivy BLE periférie (tagu). Proto CLI **přijímá** data z TX a **zapisuje** data do RX.

Bezpečný první krok je naslouchat TX bez odesílání dat:

```powershell
python cli_ble.py -c C6:04:19:D0:3F:CA --notify 6e400003-b5a3-f393-e0a9-e50e24dcca9e --listen 60
```

Zápis do RX je technicky možný, ale nemá se používat naslepo. MeshCore nad NUS pravděpodobně vyžaduje konkrétní aplikační protokol a rámcování; běžný text nemusí být platný příkaz.

## TODO checklist

### Bezpečnost a stabilita

- [x] Filtrování skenu podle názvu (`--name`), adresy (`--address`) a UUID služby (`--service`).
- [x] Parametr `--pair`; chování párování je popsané výše pro Windows i Linux.
- [x] Opakování spojení přes `--retries` a nastavitelnou mezeru `--retry-delay`.
- [x] Při chybě „device not found“ automatický nový scan, kontrola původní adresy a výpis nejbližších kandidátů.
- [x] Volitelný připojovaný souborový log `--log FILE` bez barevných ANSI kódů.

### Průzkum GATT

- [x] Přidán přepínač `--read-all-safe`: čte jen charakteristiky označené `read` a chyby hlásí po jednotlivých UUID.
- [x] Přidán výpis deskriptorů charakteristik; `--read-all-safe` vypisuje i jejich hodnoty.
- [ ] Ověřit a zdokumentovat odběr `indicate` na `Service Changed`.
- [ ] Přidat export GATT mapy do JSON pro porovnání mezi firmware verzemi.

### Nordic UART a MeshCore

- [ ] Ověřit přesný MeshCore protokol nad Nordic UART Service: rámcování, příkazy, odpovědi a kódování.
- [ ] Přidat samostatný bezpečný příkaz pro otevření NUS terminálu s TX notifikacemi a řízeným zápisem do RX.
- [ ] Přidat režim pro binární zprávy, délkové rámce a hex dumpy s časovými značkami.
- [ ] Teprve po znalosti protokolu přidat konkrétní MeshCore příkazy (stav, uzly, zprávy apod.).
- [ ] Použít `BLE_KEY` z `.env` pouze v místě, kde bude známý a ověřený autentizační postup MeshCore.

### Použitelnost

- [ ] Přidat `--no-color` pro vynucení nebarevného výstupu.
- [ ] Přidat strojově čitelný výstup `--json` pro scan, GATT služby a přijatá data.
- [ ] Přidat ukládání známých zařízení do lokální konfigurace pod přezdívkou, například `meshcore-tag`.
- [ ] Doplnit automatické testy CLI argumentů, chyb spojení a formátu JSON výstupu.
